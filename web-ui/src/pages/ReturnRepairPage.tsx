import { useState, useEffect } from 'react'
import { Steps, Button, Tag, Divider, Switch, Input, message, Dropdown, Table, Radio } from 'antd'
import {
  ScanOutlined,
  FileSearchOutlined,
  ApiOutlined,
  DollarOutlined,
  PlayCircleOutlined,
  CheckCircleFilled,
  SettingOutlined,
  SaveOutlined,
  ThunderboltOutlined,
  DownloadOutlined,
  FileTextOutlined,
  FileExcelOutlined,
  CloudOutlined,
} from '@ant-design/icons'
import { motion, AnimatePresence } from 'framer-motion'
import UploadZone from '../components/UploadZone'
import ResultTable from '../components/ResultTable'
import {
  ocrRepairOrder,
  ocrRepairCard,
  ocrRepairOrderBatch,
  ocrRepairCardBatch,
  exportRepairOrder,
  exportRepairBatch,
  mergeRepairArchive,
  getFastgptConfig,
  saveFastgptConfig,
  downloadExportFile,
  type FieldResult,
  type FastgptConfig,
  type StepFastgptConfig,
} from '../api'

const STEPS = [
  { key: 'repair_order_ocr' as keyof FastgptConfig, title: '调修单 OCR 识别', description: '维修器材调修单扫描件识别', icon: <ScanOutlined />, color: '#3378ff' },
  { key: 'repair_card_ocr' as keyof FastgptConfig,  title: '返修卡 OCR 识别', description: '返修件返修卡扫描件识别',   icon: <FileSearchOutlined />, color: '#00d4aa' },
  { key: 'archive_generation' as keyof FastgptConfig, title: '返修件档案生成', description: '调修单与返修卡信息智能融合', icon: <ApiOutlined />, color: '#f0a020' },
  { key: 'ids_match' as keyof FastgptConfig,        title: '报价方案智能生成', description: '智能生成报价方案', icon: <DollarOutlined />, color: '#a855f7' },
]

interface BatchResultItem {
  filename: string
  fields: FieldResult[]
  ocr_count: number
  timestamp: string
  fastgpt_used: boolean
  error?: string | null
}

interface StepState {
  status:  'idle' | 'processing' | 'done' | 'error'
  files:   File[]
  results: FieldResult[]
  info:    string
  progress_detail?: string
  cachedFields?: FieldResult[]
  recognizedAt?: string
  rawExports?: {
    json?: string | null
    html?: string | null
    xlsx?: string | null
  }
  fastgptUsed?: boolean
  /** 批量模式时每张图片的识别结果（用于批量导出） */
  batchResults?: BatchResultItem[]
  /** 批量模式下是否使用快速识别 */
  fastBatch?: boolean
  /** 引擎模式: 'slow' | 'fast' */
  mode?: 'slow' | 'fast'
  /** 步骤 3：返修件档案合并 */
  archiveOrderXlsx?: File | null
  archiveCardXlsx?: File | null
  archiveJoinType?: 'inner' | 'left'
  archiveStats?: {
    rows_out: number
    rows_order: number
    rows_card: number
    join_type: string
    duplicate_key_groups: number
  }
  archiveExportFilename?: string
}

function initState(): StepState {
  return {
    status: 'idle',
    files: [],
    results: [],
    info: '',
    progress_detail: '',
    cachedFields: undefined,
    recognizedAt: undefined,
    rawExports: undefined,
    fastgptUsed: undefined,
    batchResults: undefined,
    fastBatch: false,
    mode: 'slow',
    archiveOrderXlsx: null,
    archiveCardXlsx: null,
    archiveJoinType: 'inner',
    archiveStats: undefined,
    archiveExportFilename: undefined,
  }
}

const EMPTY_FGPT: StepFastgptConfig = { api_url: '', api_key: '', appid: '', enabled: false }
const DEFAULT_CFG: FastgptConfig = {
  repair_order_ocr:   { ...EMPTY_FGPT },
  repair_card_ocr:    { ...EMPTY_FGPT },
  archive_generation: { ...EMPTY_FGPT },
  ids_match:         { ...EMPTY_FGPT },
  quote_generation:  { ...EMPTY_FGPT },
}

const IDS_MOCK: FieldResult[] = [
  { key: 'ids_no',  field: 'IDS编号',    value: 'IDS-HYD-20240315', confidence: 0.98 },
  { key: 'status',  field: '器件状态',   value: '在修',              confidence: 0.97 },
  { key: 'history', field: '历史记录',   value: '2次历史维修',        confidence: 0.95 },
  { key: 'conf',    field: '匹配置信度', value: '98.5%',             confidence: 0.99 },
]
const QUOTE_MOCK: FieldResult[] = [
  { key: 'price',    field: '报价金额', value: '¥ 12,800.00', confidence: 1.0 },
  { key: 'labor',    field: '工时费用', value: '¥ 3,200.00',  confidence: 1.0 },
  { key: 'material', field: '材料费用', value: '¥ 9,600.00',  confidence: 1.0 },
  { key: 'total',    field: '总计',     value: '¥ 12,800.00', confidence: 1.0 },
]

// ─── FastGPT 配置面板 ────────────────────────────────────────────────────────
interface FgptPanelProps {
  stepKey:  keyof FastgptConfig
  cfg:      FastgptConfig
  saving:   boolean
  onChange: (key: keyof FastgptConfig, patch: Partial<StepFastgptConfig>) => void
  onSave:   () => void
}
function FgptPanel({ stepKey, cfg, saving, onChange, onSave }: FgptPanelProps) {
  const c = cfg[stepKey]
  const inputStyle: React.CSSProperties = { background: '#0d1117', borderColor: '#30363d', color: '#e6edf3' }
  return (
    <div style={{ background: '#0d1117', border: '1px solid #21262d', borderRadius: 10, padding: '16px 20px', marginBottom: 20 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 14 }}>
        <SettingOutlined style={{ color: '#7d8590' }} />
        <span style={{ color: '#e6edf3', fontWeight: 600, fontSize: 13 }}>FastGPT 接口配置</span>
        <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 8 }}>
          <Switch size="small" checked={c.enabled} onChange={(v) => onChange(stepKey, { enabled: v })} />
          <span style={{ color: c.enabled ? '#00d4aa' : '#484f58', fontSize: 12, fontWeight: 600 }}>
            {c.enabled ? '已启用' : '未启用'}
          </span>
          {c.enabled && (
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4, background: 'rgba(0,212,170,0.1)', border: '1px solid rgba(0,212,170,0.3)', borderRadius: 20, padding: '2px 8px', fontSize: 11, color: '#00d4aa', fontWeight: 600 }}>
              <ThunderboltOutlined style={{ fontSize: 10 }} /> FastGPT 已启用
            </span>
          )}
        </div>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '10px 16px' }}>
        <div>
          <div style={{ color: '#7d8590', fontSize: 11, fontWeight: 600, marginBottom: 5 }}>API 地址</div>
          <Input style={inputStyle} placeholder="https://cloud.fastgpt.cn/api/v1/chat/completions" value={c.api_url} onChange={(e) => onChange(stepKey, { api_url: e.target.value })} disabled={!c.enabled} />
        </div>
        <div>
          <div style={{ color: '#7d8590', fontSize: 11, fontWeight: 600, marginBottom: 5 }}>应用 ID (appid)</div>
          <Input style={inputStyle} placeholder="your-app-id" value={c.appid} onChange={(e) => onChange(stepKey, { appid: e.target.value })} disabled={!c.enabled} />
        </div>
        <div style={{ gridColumn: '1 / -1' }}>
          <div style={{ color: '#7d8590', fontSize: 11, fontWeight: 600, marginBottom: 5 }}>API 密钥</div>
          <Input.Password style={inputStyle} placeholder="fastgpt-xxxxxxxxxxxx" value={c.api_key} onChange={(e) => onChange(stepKey, { api_key: e.target.value })} disabled={!c.enabled} />
        </div>
      </div>
      <div style={{ marginTop: 12, display: 'flex', justifyContent: 'flex-end' }}>
        <Button size="small" icon={<SaveOutlined />} loading={saving} onClick={onSave}
          style={{ background: '#21262d', borderColor: '#30363d', color: '#e6edf3', fontSize: 12 }}>
          保存配置
        </Button>
      </div>
    </div>
  )
}

// ─── 主页面 ───────────────────────────────────────────────────────────────────
export default function ReturnRepairPage() {
  const [current,    setCurrent]    = useState(0)
  const [stepStates, setStepStates] = useState<StepState[]>(STEPS.map(initState))
  const [fgptCfg,    setFgptCfg]   = useState<FastgptConfig>(DEFAULT_CFG)
  const [cfgLoading, setCfgLoading] = useState(true)
  const [saving,     setSaving]     = useState(false)
  const [showCfg,    setShowCfg]    = useState<boolean[]>(STEPS.map(() => false))
  const [messageApi, contextHolder] = message.useMessage()

  useEffect(() => {
    getFastgptConfig()
      .then((cfg) => setFgptCfg(cfg))
      .catch(() => messageApi.warning('无法加载 FastGPT 配置，使用默认值'))
      .finally(() => setCfgLoading(false))
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  const updateStep = (idx: number, patch: Partial<StepState>) =>
    setStepStates((prev) => prev.map((s, i) => (i === idx ? { ...s, ...patch } : s)))

  const patchFgpt = (key: keyof FastgptConfig, patch: Partial<StepFastgptConfig>) =>
    setFgptCfg((prev) => ({ ...prev, [key]: { ...prev[key], ...patch } }))

  const handleSaveCfg = async () => {
    setSaving(true)
    try {
      await saveFastgptConfig(fgptCfg)
      messageApi.success('FastGPT 配置已保存')
    } catch {
      messageApi.error('保存配置失败')
    } finally {
      setSaving(false)
    }
  }

  // 模拟详细进度动画
  const animateProgress = (idx: number, steps: string[]) => {
    let stepIdx = 0
    const interval = setInterval(() => {
      if (stepIdx < steps.length) {
        updateStep(idx, { progress_detail: steps[stepIdx] })
        stepIdx++
      } else {
        clearInterval(interval)
      }
    }, 800)
    return interval
  }

  const handleProcess = async (idx: number) => {
    // 步骤 2、3 为模拟链路（档案生成、IDS+报价一体化）
    if (idx === 2) {
      const st = stepStates[2]
      if (!st.archiveOrderXlsx || !st.archiveCardXlsx) {
        messageApi.warning('请分别上传调修单批量与返修卡批量的 .xlsx 文件')
        return
      }
      updateStep(2, { status: 'processing', progress_detail: '正在读取与匹配表格...', info: '' })
      try {
        const resp = await mergeRepairArchive(st.archiveOrderXlsx, st.archiveCardXlsx, st.archiveJoinType ?? 'inner')
        const filename =
          resp.filename ||
          (resp.exports?.excel ? resp.exports.excel.split(/[/\\]/).pop() : undefined) ||
          '返修件档案.xlsx'
        if (resp.exports?.excel) {
          downloadExportFile(filename)
        }
        updateStep(2, {
          status: 'done',
          progress_detail: '',
          archiveStats: {
            rows_out: resp.rows_out,
            rows_order: resp.rows_order,
            rows_card: resp.rows_card,
            join_type: resp.join_type,
            duplicate_key_groups: resp.duplicate_key_groups,
          },
          archiveExportFilename: filename,
          info: `已生成 ${resp.rows_out} 条档案记录（调修单 ${resp.rows_order} 行，返修卡 ${resp.rows_card} 行）`,
        })
        messageApi.success('返修件档案已生成并开始下载')
      } catch (e: unknown) {
        const msg = e instanceof Error ? e.message : String(e)
        updateStep(2, { status: 'error', info: msg, progress_detail: '' })
        messageApi.error(`档案生成失败：${msg}`)
      }
      return
    }
    if (idx === 3) {
      updateStep(idx, { status: 'processing', progress_detail: '正在连接 IDS 系统...' })
      const progressSteps = [
        '正在连接 IDS 系统...',
        '正在获取设备信息...',
        '正在匹配置信度计算...',
        '正在汇总报价数据...',
        '正在生成报价方案...',
        '正在计算费用明细...',
        '报价方案生成完成',
      ]
      const interval = animateProgress(idx, progressSteps)
      await new Promise((r) => setTimeout(r, progressSteps.length * 800 + 400))
      clearInterval(interval)
      updateStep(idx, { status: 'done', results: [...IDS_MOCK, ...QUOTE_MOCK], info: '', progress_detail: '' })
      return
    }
    const state = stepStates[idx]
    if (state.files.length === 0) { messageApi.warning('请先上传图片文件'); return }

    const sc = fgptCfg[STEPS[idx].key]
    const fastBatch = state.files.length > 1
    const mode = state.mode ?? 'slow'
    const commonOpts = sc.enabled
      ? { useFastgpt: true, apiUrl: sc.api_url, apiKey: sc.api_key, appid: sc.appid, fastBatch, mode }
      : { useFastgpt: false, fastBatch, mode }

    if (fastBatch) {
      // ── 批量模式 ──────────────────────────────────────────────
      updateStep(idx, { status: 'processing', progress_detail: `正在批量识别 ${state.files.length} 张图片...`, fastBatch: true, batchResults: [], results: [] })
      try {
        const resp = idx === 0
          ? await ocrRepairOrderBatch(state.files, commonOpts)
          : await ocrRepairCardBatch(state.files, commonOpts)

        if (!resp) {
          throw new Error('后端返回空响应，请检查服务是否正常运行')
        }
        const items: BatchResultItem[] = resp.results.map(r => ({
          filename: r.filename,
          fields: r.fields,
          ocr_count: r.ocr_count,
          timestamp: r.timestamp,
          fastgpt_used: r.fastgpt_used,
          error: r.error,
        }))
        const successCount = items.filter(r => !r.error).length
        const batchMode = resp.mode
        updateStep(idx, {
          status: 'done',
          batchResults: items,
          results: [],
          info: `批量识别完成：${successCount}/${state.files.length} 张成功`,
          progress_detail: '',
          mode: batchMode === 'slow' || batchMode === 'fast' ? batchMode : 'slow',
        })
        messageApi.success(`批量识别完成：${successCount}/${state.files.length} 张成功`)
      } catch (e: unknown) {
        const msg = e instanceof Error ? e.message : String(e)
        updateStep(idx, { status: 'error', info: msg, progress_detail: '' })
        messageApi.error(`批量识别失败：${msg}`)
      }
    } else {
      // ── 单张模式 ──────────────────────────────────────────────
      updateStep(idx, { status: 'processing', progress_detail: '正在准备识别...', fastBatch: false })
      const progressSteps = ['正在加载 OCR 引擎...', '正在进行文本检测...', '正在进行文本识别...', '正在提取字段信息...', '正在生成结果...']
      const interval = animateProgress(idx, progressSteps)
      try {
        const resp = idx === 0
          ? await ocrRepairOrder(state.files[0], commonOpts)
          : await ocrRepairCard(state.files[0], commonOpts)
        clearInterval(interval)
        if (!resp) {
          throw new Error('后端返回空响应，请检查服务是否正常运行')
        }
        updateStep(idx, {
          status: 'done',
          results: resp.fields,
          cachedFields: resp.fields,
          recognizedAt: resp.timestamp,
          info: `识别 ${resp.ocr_count} 个文本块 · ${resp.timestamp}`,
          progress_detail: '',
          rawExports: resp.raw_exports,
          fastgptUsed: resp.fastgpt_used,
          fastBatch: resp.fast_batch,
          mode: resp.mode,
        })
        messageApi.success(`步骤 ${idx + 1} 识别完成`)
      } catch (e: unknown) {
        clearInterval(interval)
        const msg = e instanceof Error ? e.message : String(e)
        updateStep(idx, { status: 'error', info: msg, progress_detail: '' })
        messageApi.error(`识别失败：${msg}`)
      }
    }
  }

  // 调修单/返修卡识别结果导出
  const handleExport = async (idx: number, fmt: 'excel' | 'csv' | 'json' | 'all') => {
    const state = stepStates[idx]
    const fields = state.cachedFields ?? state.results

    // ── 批量导出 ────────────────────────────────────────────
    if (state.batchResults && state.batchResults.length > 0) {
      const docType = idx === 0 ? 'repair_order' : 'repair_card'
      // 构造导出行（只有识别成功的行）
      const rows = state.batchResults
        .filter(r => !r.error && r.fields.length > 0)
        .map(r => ({
          image_name: r.filename,
          recognition_time: r.timestamp,
          fields: r.fields,
        }))
      if (rows.length === 0) { messageApi.warning('没有可导出的识别结果'); return }
      // 找出与 rows 顺序对应的原图 File
      const nameToFile: Record<string, File> = {}
      for (const f of state.files) nameToFile[f.name] = f
      const images = rows.map(r => nameToFile[r.image_name]).filter(Boolean) as File[]
      try {
        const resp = await exportRepairBatch(rows, docType, fmt, images)
        const exports = resp.exports ?? {}
        if (Object.keys(exports).length > 0) {
          for (const [, filePath] of Object.entries(exports)) {
            const filename = filePath.split(/[\\/]/).pop() || 'export'
            downloadExportFile(filename)
            await new Promise((r) => setTimeout(r, 300))
          }
          messageApi.success('批量导出成功')
        } else {
          messageApi.warning('未能获取导出文件')
        }
      } catch (e: unknown) {
        const msg = e instanceof Error ? e.message : String(e)
        messageApi.error(`批量导出失败：${msg}`)
      }
      return
    }

    // ── 单张导出 ────────────────────────────────────────────
    if (fields.length === 0) { messageApi.warning('没有可导出的识别结果'); return }
    try {
      const exportOpts =
        idx === 0
          ? { docType: 'repair_order' as const, imageFile: state.files[0], imageName: state.files[0]?.name ?? '', recognitionTime: state.recognizedAt ?? '' }
          : { docType: 'repair_card' as const, imageFile: state.files[0], imageName: state.files[0]?.name ?? '', recognitionTime: state.recognizedAt ?? '' }
      const resp = await exportRepairOrder(fields, fmt, exportOpts)
      const exports = resp.exports ?? {}
      if (Object.keys(exports).length > 0) {
        for (const [, filePath] of Object.entries(exports)) {
          const filename = filePath.split(/[\\/]/).pop() || 'export'
          downloadExportFile(filename)
          await new Promise((r) => setTimeout(r, 300))
        }
        messageApi.success('导出成功')
      } else {
        messageApi.warning('未能获取导出文件')
      }
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e)
      messageApi.error(`导出失败：${msg}`)
    }
  }

  // 下载原始表格文件（JSON/HTML/Excel）
  const handleExportRaw = async (idx: number, type: 'json' | 'html' | 'xlsx') => {
    const state = stepStates[idx]
    const rawPath = type === 'json' ? state.rawExports?.json : type === 'html' ? state.rawExports?.html : state.rawExports?.xlsx
    if (!rawPath) {
      messageApi.warning('没有可下载的原始表格文件')
      return
    }
    const filename = rawPath.split(/[\\/]/).pop() || `raw_table.${type}`
    downloadExportFile(filename)
  }

  const step  = STEPS[current]
  const state = stepStates[current]
  const sc    = fgptCfg[step.key]
  const isMergedIdsQuoteStep = current === STEPS.length - 1 && step.key === 'ids_match'
  const mergedFgptEnabled = fgptCfg.ids_match.enabled || fgptCfg.quote_generation.enabled

  const antStepItems = STEPS.map((s, i) => ({
    title: s.title,
    description: s.description,
    icon:
      stepStates[i].status === 'done' ? (
        <CheckCircleFilled style={{ color: '#00d4aa' }} />
      ) : i === current ? (
        <div style={{ width: 32, height: 32, borderRadius: '50%', background: s.color, display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#fff', fontSize: 16, boxShadow: `0 0 12px ${s.color}80` }}>
          {s.icon}
        </div>
      ) : undefined,
  }))

  return (
    <div style={{ padding: '40px 24px', maxWidth: 1100, margin: '0 auto' }}>
      {contextHolder}

      {/* 页头 */}
      <motion.div initial={{ opacity: 0, y: -16 }} animate={{ opacity: 1, y: 0 }} className="mb-10">
        <div className="flex items-center gap-3 mb-3">
          <div style={{ width: 40, height: 40, borderRadius: 10, background: 'linear-gradient(135deg, #1a57f5, #3378ff)', display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#fff', fontSize: 18, boxShadow: '0 4px 16px rgba(51,120,255,0.4)' }}>
            <DollarOutlined />
          </div>
          <div>
            <h1 style={{ margin: 0, fontSize: 24, fontWeight: 700, color: '#e6edf3' }}>地面返修件报价智能链路</h1>
            <p style={{ margin: 0, color: '#7d8590', fontSize: 13 }}>按步骤完成各阶段识别，最终生成报价数据</p>
          </div>
        </div>
      </motion.div>

      {/* Steps 导航条 */}
      <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: 0.15 }}
        style={{ background: '#161b22', border: '1px solid #21262d', borderRadius: 14, padding: '28px 32px', marginBottom: 32 }}>
        <Steps current={current} items={antStepItems}
          onChange={(i) => setCurrent(i)} />
      </motion.div>

      {/* 当前步骤内容 */}
      <AnimatePresence mode="wait">
        <motion.div key={current} initial={{ opacity: 0, x: 30 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: -30 }} transition={{ duration: 0.3, ease: 'easeOut' }}>
          <div style={{ background: '#161b22', border: `1px solid ${step.color}30`, borderRadius: 14, padding: 28, position: 'relative', overflow: 'hidden' }}>

            {/* 顶部彩色线 */}
            <div style={{ position: 'absolute', top: 0, left: 0, right: 0, height: 3, background: `linear-gradient(90deg, ${step.color}, transparent)`, borderRadius: '14px 14px 0 0' }} />

            {/* 步骤标题行 */}
            <div className="flex items-center gap-3 mb-5">
              <div style={{ width: 36, height: 36, borderRadius: 10, background: `${step.color}20`, border: `1px solid ${step.color}40`, display: 'flex', alignItems: 'center', justifyContent: 'center', color: step.color, fontSize: 16 }}>
                {step.icon}
              </div>
              <div>
                <div style={{ color: '#e6edf3', fontWeight: 600, fontSize: 16 }}>步骤 {current + 1} / {STEPS.length} — {step.title}</div>
                <div style={{ color: '#7d8590', fontSize: 13 }}>{step.description}</div>
              </div>
              <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 8 }}>
                {/* FastGPT 状态徽章 */}
                {current !== 2 && (isMergedIdsQuoteStep ? mergedFgptEnabled : sc.enabled) && (
                  <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4, background: 'rgba(0,212,170,0.1)', border: '1px solid rgba(0,212,170,0.3)', borderRadius: 20, padding: '2px 10px', fontSize: 11, color: '#00d4aa', fontWeight: 600 }}>
                    <ThunderboltOutlined style={{ fontSize: 10 }} /> FastGPT 已启用
                  </span>
                )}
                <Tag style={{ background: `${step.color}18`, border: `1px solid ${step.color}40`, color: step.color, fontFamily: "'JetBrains Mono', monospace", fontSize: 11 }}>
                  {state.status === 'done' ? '✓ 已完成' : state.status === 'processing' ? '处理中' : state.status === 'error' ? '✗ 失败' : '待处理'}
                </Tag>
                {/* 配置按钮 */}
                {current !== 2 && (
                  <Button
                    size="small"
                    icon={<SettingOutlined />}
                    onClick={() => setShowCfg((prev) => prev.map((v, i) => (i === current ? !v : v)))}
                    style={{ background: showCfg[current] ? `${step.color}20` : '#21262d', borderColor: showCfg[current] ? step.color : '#30363d', color: showCfg[current] ? step.color : '#7d8590', fontSize: 12 }}
                  >
                    {cfgLoading ? '加载中...' : 'FastGPT 配置'}
                  </Button>
                )}
              </div>
            </div>

            {/* FastGPT 配置面板（可折叠） */}
            <AnimatePresence>
              {showCfg[current] && current !== 2 && (
                <motion.div initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: 'auto' }} exit={{ opacity: 0, height: 0 }} transition={{ duration: 0.2 }} style={{ overflow: 'hidden' }}>
                  {isMergedIdsQuoteStep ? (
                    <>
                      <FgptPanel stepKey="ids_match" cfg={fgptCfg} saving={saving} onChange={patchFgpt} onSave={handleSaveCfg} />
                      <FgptPanel stepKey="quote_generation" cfg={fgptCfg} saving={saving} onChange={patchFgpt} onSave={handleSaveCfg} />
                    </>
                  ) : (
                    <FgptPanel stepKey={step.key} cfg={fgptCfg} saving={saving} onChange={patchFgpt} onSave={handleSaveCfg} />
                  )}
                </motion.div>
              )}
            </AnimatePresence>

            {/* 上传区 — 仅步骤0、1显示 */}
            {current < 2 && (
              <div className="mb-6">
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 10 }}>
                  <div style={{ color: '#7d8590', fontSize: 13 }}>上传扫描件图片</div>
                </div>
                {/* 引擎模式选择 */}
                <div style={{ marginBottom: 12, display: 'flex', alignItems: 'center', gap: 16 }}>
                  <span style={{ color: '#7d8590', fontSize: 13 }}>引擎模式：</span>
                  <Radio.Group
                    value={state.mode ?? 'slow'}
                    onChange={(e) => updateStep(current, { mode: e.target.value })}
                    buttonStyle="solid"
                    size="small"
                  >
                    <Radio.Button value="slow" disabled={state.files.length > 1}>
                      <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                        <ThunderboltOutlined style={{ fontSize: 11 }} /> 正常模式
                      </span>
                    </Radio.Button>
                    <Radio.Button value="fast">
                      <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                        <ThunderboltOutlined style={{ fontSize: 11 }} /> 快速模式
                      </span>
                    </Radio.Button>
                  </Radio.Group>
                  <span style={{ color: '#484f58', fontSize: 11 }}>
                    {state.mode === 'fast' ? '（纯 OCR，仅文本检测识别，不生成表格）' :
                     state.files.length > 1 ? '（批量模式仅支持快速模式）' : '（PP-StructureV3 完整流程，含表格结构识别）'}
                  </span>
                </div>
                <UploadZone
                  onFiles={(files) =>
                    updateStep(current, {
                      files,
                      status: 'idle',
                      results: [],
                      cachedFields: undefined,
                      recognizedAt: undefined,
                      rawExports: undefined,
                      fastgptUsed: undefined,
                      batchResults: undefined,
                      fastBatch: false,
                    })
                  }
                  multiple={true}
                />
              </div>
            )}

            {/* 返修件档案：上传两个批量 xlsx */}
            {current === 2 && (
              <div style={{ marginBottom: 24 }}>
                <div
                  style={{
                    padding: 20,
                    borderRadius: 10,
                    background: '#1c2128',
                    border: '1px solid #21262d',
                    marginBottom: 20,
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 12 }}>
                    <ApiOutlined style={{ fontSize: 22, color: '#f0a020' }} />
                    <span style={{ color: '#e6edf3', fontWeight: 600, fontSize: 14 }}>上传前两步导出的批量 Excel（.xlsx）</span>
                  </div>
                  <p style={{ color: '#7d8590', fontSize: 12, margin: '0 0 10px', lineHeight: 1.6 }}>
                    四键完全一致视为同一返修件：<b style={{ color: '#a8b0ba' }}>装备型号</b>↔产品代号、<b style={{ color: '#a8b0ba' }}>器材名称</b>↔返修件名称、
                    <b style={{ color: '#a8b0ba' }}>器件编号</b>↔批次号、<b style={{ color: '#a8b0ba' }}>型（图）号</b>↔图号。键值会自动去首尾空格并转为字符串比对。
                  </p>
                  <ul style={{ color: '#484f58', fontSize: 11, margin: 0, paddingLeft: 18 }}>
                    <li>输出列：返修卡侧字段 + 调修单号 / 邮寄地址 / 进厂时间；两侧原图缩略图固定在最后两列（返修卡原图、调修单原图），按列宽缩放，避免遮挡文字。</li>
                    <li>文件需与本系统批量导出模板列名一致（首个工作表）。</li>
                  </ul>
                </div>
                <div
                  style={{
                    display: 'grid',
                    gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))',
                    gap: 16,
                    marginBottom: 16,
                  }}
                >
                  <div>
                    <div style={{ color: '#7d8590', fontSize: 12, fontWeight: 600, marginBottom: 8 }}>调修单批量识别表</div>
                    <UploadZone
                      accept={{
                        'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': ['.xlsx'],
                      }}
                      multiple={false}
                      label="拖拽或点击上传调修单批量 .xlsx"
                      hint="步骤 1 批量导出文件"
                      onFiles={(files) =>
                        updateStep(2, {
                          archiveOrderXlsx: files[0] ?? null,
                          status: 'idle',
                          archiveStats: undefined,
                          archiveExportFilename: undefined,
                          info: '',
                        })
                      }
                    />
                    {state.archiveOrderXlsx && (
                      <p style={{ color: '#484f58', fontSize: 11, marginTop: 8, marginBottom: 0 }}>
                        已绑定文件：{state.archiveOrderXlsx.name}
                      </p>
                    )}
                  </div>
                  <div>
                    <div style={{ color: '#7d8590', fontSize: 12, fontWeight: 600, marginBottom: 8 }}>返修卡批量识别表</div>
                    <UploadZone
                      accept={{
                        'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': ['.xlsx'],
                      }}
                      multiple={false}
                      label="拖拽或点击上传返修卡批量 .xlsx"
                      hint="步骤 2 批量导出文件"
                      onFiles={(files) =>
                        updateStep(2, {
                          archiveCardXlsx: files[0] ?? null,
                          status: 'idle',
                          archiveStats: undefined,
                          archiveExportFilename: undefined,
                          info: '',
                        })
                      }
                    />
                    {state.archiveCardXlsx && (
                      <p style={{ color: '#484f58', fontSize: 11, marginTop: 8, marginBottom: 0 }}>
                        已绑定文件：{state.archiveCardXlsx.name}
                      </p>
                    )}
                  </div>
                </div>
                <div style={{ display: 'flex', alignItems: 'center', flexWrap: 'wrap', gap: 12, marginBottom: 8 }}>
                  <span style={{ color: '#7d8590', fontSize: 13 }}>合并方式</span>
                  <Radio.Group
                    value={state.archiveJoinType ?? 'inner'}
                    onChange={(e) => updateStep(2, { archiveJoinType: e.target.value })}
                    buttonStyle="solid"
                    size="small"
                  >
                    <Radio.Button value="inner">内连接（仅双方四键都匹配）</Radio.Button>
                    <Radio.Button value="left">左连接（以返修卡为主，未匹配则调修单字段为空）</Radio.Button>
                  </Radio.Group>
                </div>
              </div>
            )}

            {/* IDS 报价一体化步骤 — 待处理说明 */}
            {current === 3 && state.status !== 'done' && (
              <div style={{ padding: 24, borderRadius: 10, background: '#1c2128', border: '1px solid #21262d', marginBottom: 24, textAlign: 'center' }}>
                <DollarOutlined style={{ fontSize: 36, color: '#a855f7', display: 'block', marginBottom: 12 }} />
                <p style={{ color: '#7d8590', margin: 0 }}>提取IDS系统数据，智能生成报价方案</p>
              </div>
            )}

            {/* 操作按钮 */}
            <div className="flex gap-3 mb-6">
              <Button
                type="primary"
                icon={<PlayCircleOutlined />}
                loading={state.status === 'processing'}
                disabled={
                  (current < 2 && state.files.length === 0) ||
                  (current === 2 && (!state.archiveOrderXlsx || !state.archiveCardXlsx))
                }
                onClick={() => handleProcess(current)}
                style={{ background: step.color, borderColor: step.color, boxShadow: `0 4px 14px ${step.color}50` }}
              >
                {state.status === 'processing'
                  ? current === 2
                    ? '正在生成档案...'
                    : '识别中...'
                  : current === 2
                    ? '生成返修件档案'
                    : state.files.length > 1
                      ? `批量识别 ${state.files.length} 张`
                      : '开始处理'}
              </Button>
              {/* 进度详情显示 */}
              {state.status === 'processing' && state.progress_detail && (
                <motion.div
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: 8,
                    padding: '6px 14px',
                    borderRadius: 8,
                    background: `${step.color}12`,
                    border: `1px solid ${step.color}30`,
                    color: '#7d8590',
                    fontSize: 13,
                  }}
                >
                  <motion.div
                    animate={{ rotate: 360 }}
                    transition={{ duration: 1, repeat: Infinity, ease: 'linear' }}
                    style={{
                      width: 14,
                      height: 14,
                      border: `2px solid ${step.color}50`,
                      borderTopColor: step.color,
                      borderRadius: '50%',
                    }}
                  />
                  {state.progress_detail}
                </motion.div>
              )}
              {state.status === 'done' && current < STEPS.length - 1 && (
                <Button onClick={() => setCurrent(current + 1)}
                  style={{ background: '#1c2128', borderColor: '#30363d', color: '#e6edf3' }}>
                  下一步 →
                </Button>
              )}
            </div>

            {/* 识别结果 */}
            <AnimatePresence>
              {/* 批量模式：显示结果列表 */}
              {state.status === 'done' && state.batchResults && state.batchResults.length > 0 && (
                <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
                  <Divider style={{ borderColor: '#21262d', margin: '0 0 16px' }} />
                  {state.info && <p style={{ color: '#7d8590', fontSize: 12, marginBottom: 12 }}>{state.info}</p>}
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
                    <div style={{ color: '#7d8590', fontSize: 13 }}>批量识别结果（共 {state.batchResults.length} 张）</div>
                    <div style={{ color: '#00d4aa', fontSize: 12 }}>
                      {state.batchResults.filter(r => !r.error).length} 成功 / {state.batchResults.length} 总数
                    </div>
                  </div>
                  <div className="mb-4" style={{ maxHeight: 360, overflowY: 'auto', borderRadius: 8, border: '1px solid #21262d' }}>
                    <Table
                      size="small"
                      pagination={false}
                      dataSource={state.batchResults.map((r, i) => ({ ...r, key: i }))}
                      columns={[
                        { title: '图片名称', dataIndex: 'filename', key: 'filename', render: (v) => <span style={{ color: '#e6edf3', fontSize: 12 }}>{v}</span> },
                        { title: '识别状态', dataIndex: 'error', key: 'error', width: 90, render: (e) => e ? <span style={{ color: '#f85149', fontSize: 12 }}>失败</span> : <span style={{ color: '#00d4aa', fontSize: 12 }}>成功</span> },
                        { title: '文本块数', dataIndex: 'ocr_count', key: 'ocr_count', width: 80, render: (v) => <span style={{ color: '#7d8590', fontSize: 12 }}>{v}</span> },
                        { title: '识别时间', dataIndex: 'timestamp', key: 'timestamp', width: 160, render: (v) => <span style={{ color: '#484f58', fontSize: 12 }}>{v}</span> },
                        { title: '错误信息', dataIndex: 'error', key: 'err', render: (e) => e ? <span style={{ color: '#f85149', fontSize: 11, maxWidth: 200, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', display: 'block' }} title={e}>{e}</span> : <span style={{ color: '#484f58', fontSize: 12 }}>-</span> },
                      ]}
                    />
                  </div>
                  {/* 批量导出（批量模式不显示原表输出，因为 fast_batch=True 时没有原表） */}
                  <div className="flex gap-2 mb-4">
                    <Dropdown
                      menu={{
                        items: [
                          { key: 'excel', icon: <FileExcelOutlined />, label: '导出 Excel (.xlsx)', onClick: () => handleExport(current, 'excel') },
                          { key: 'csv', icon: <FileTextOutlined />, label: '导出 CSV (.csv)', onClick: () => handleExport(current, 'csv') },
                          { key: 'json', icon: <CloudOutlined />, label: '导出 JSON (.json)', onClick: () => handleExport(current, 'json') },
                          { type: 'divider' as const },
                          { key: 'all', icon: <DownloadOutlined />, label: '导出全部格式', onClick: () => handleExport(current, 'all') },
                        ],
                      }}
                      trigger={['click']}
                      placement="bottomLeft"
                    >
                      <Button icon={<DownloadOutlined />} style={{ background: '#1f883d', borderColor: '#1f883d', color: '#fff' }}>
                        批量导出
                      </Button>
                    </Dropdown>
                  </div>
                </motion.div>
              )}
              {/* 单张模式：显示字段表格 */}
              {state.status === 'done' && state.results.length > 0 && !state.batchResults && (
                <motion.div initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: 'auto' }} exit={{ opacity: 0, height: 0 }}>
                  <Divider style={{ borderColor: '#21262d', margin: '0 0 16px' }} />
                  {state.info && <p style={{ color: '#7d8590', fontSize: 12, marginBottom: 12 }}>{state.info}</p>}
                  {/* 调修单/返修卡专属导出按钮组（与通用表格识别一致的样式） */}
                  {current < 2 && (
                    <div className="flex gap-2 mb-4 items-center flex-wrap">
                      {/* 识别结果导出：使用 FastGPT 提取的字段 + 原图 */}
                      <Dropdown
                        menu={{
                          items: [
                            {
                              key: 'excel',
                              icon: <FileExcelOutlined />,
                              label: '导出 Excel (.xlsx)',
                              onClick: () => handleExport(current, 'excel'),
                            },
                            {
                              key: 'csv',
                              icon: <FileTextOutlined />,
                              label: '导出 CSV (.csv)',
                              onClick: () => handleExport(current, 'csv'),
                            },
                            {
                              key: 'json',
                              icon: <CloudOutlined />,
                              label: '导出 JSON (.json)',
                              onClick: () => handleExport(current, 'json'),
                            },
                            { type: 'divider' as const },
                            {
                              key: 'all',
                              icon: <DownloadOutlined />,
                              label: '导出全部格式',
                              onClick: () => handleExport(current, 'all'),
                            },
                          ],
                        }}
                        trigger={['click']}
                        placement="bottomLeft"
                      >
                        <Button
                          icon={<DownloadOutlined />}
                          style={{ background: '#1f883d', borderColor: '#1f883d', color: '#fff' }}
                        >
                          识别结果导出
                        </Button>
                      </Dropdown>

                      {/* 原表输出：PPStructureV3 原始表格 */}
                      <Dropdown
                        menu={{
                          items: [
                            {
                              key: 'raw_json',
                              icon: <CloudOutlined />,
                              label: 'JSON (.json)',
                              onClick: () => handleExportRaw(current, 'json'),
                              disabled: !state.rawExports?.json,
                            },
                            {
                              key: 'raw_html',
                              icon: <FileTextOutlined />,
                              label: 'HTML (.html)',
                              onClick: () => handleExportRaw(current, 'html'),
                              disabled: !state.rawExports?.html,
                            },
                            {
                              key: 'raw_xlsx',
                              icon: <FileExcelOutlined />,
                              label: 'Excel (.xlsx)',
                              onClick: () => handleExportRaw(current, 'xlsx'),
                              disabled: !state.rawExports?.xlsx,
                            },
                          ],
                        }}
                        trigger={['click']}
                        placement="bottomLeft"
                      >
                        <Button
                          icon={<DownloadOutlined />}
                          style={{ background: '#21262d', borderColor: '#30363d', color: '#e6edf3' }}
                          disabled={!state.rawExports?.json && !state.rawExports?.html && !state.rawExports?.xlsx}
                        >
                          原表输出
                        </Button>
                      </Dropdown>
                    </div>
                  )}
                  <ResultTable
                    data={state.results}
                    onExport={current < 2 ? () => handleExport(current, 'excel') : undefined}
                  />
                </motion.div>
              )}
              {current === 2 && state.status === 'done' && state.archiveStats && (
                <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
                  <Divider style={{ borderColor: '#21262d', margin: '0 0 16px' }} />
                  {state.info && <p style={{ color: '#e6edf3', fontSize: 14, marginBottom: 10 }}>{state.info}</p>}
                  <p style={{ color: '#7d8590', fontSize: 12, marginBottom: 14 }}>
                    合并方式：{state.archiveStats.join_type === 'inner' ? '内连接' : '左连接'} · 存在多行同四键的组数：{state.archiveStats.duplicate_key_groups}
                  </p>
                  {state.archiveExportFilename && (
                    <Button
                      icon={<DownloadOutlined />}
                      onClick={() => downloadExportFile(state.archiveExportFilename!)}
                      style={{ background: '#1f883d', borderColor: '#1f883d', color: '#fff' }}
                    >
                      再次下载 返修件档案
                    </Button>
                  )}
                </motion.div>
              )}
            </AnimatePresence>

            {/* 错误信息 */}
            {state.status === 'error' && (
              <div style={{ padding: 12, borderRadius: 8, background: 'rgba(201,42,42,0.1)', border: '1px solid rgba(201,42,42,0.3)', color: '#ff6b6b', fontSize: 13 }}>
                ✗ {state.info}
              </div>
            )}
          </div>
        </motion.div>
      </AnimatePresence>

      {/* 全部完成提示 */}
      <AnimatePresence>
        {stepStates.every((s) => s.status === 'done') && (
          <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.3 }}
            style={{ marginTop: 24, padding: 24, borderRadius: 14, background: 'linear-gradient(135deg, rgba(0,212,170,0.08), rgba(51,120,255,0.08))', border: '1px solid rgba(0,212,170,0.3)', textAlign: 'center' }}>
            <CheckCircleFilled style={{ fontSize: 40, color: '#00d4aa', marginBottom: 12, display: 'block' }} />
            <p style={{ color: '#e6edf3', fontSize: 16, fontWeight: 600, margin: '0 0 4px' }}>链路全部完成！</p>
            <p style={{ color: '#7d8590', margin: 0 }}>所有步骤已处理完毕，报价数据已生成</p>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}

