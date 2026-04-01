import { useState, useEffect } from 'react'
import { Steps, Button, Tag, Divider, Switch, Input, message } from 'antd'
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
} from '@ant-design/icons'
import { motion, AnimatePresence } from 'framer-motion'
import UploadZone from '../components/UploadZone'
import ResultTable from '../components/ResultTable'
import {
  ocrRepairOrder,
  ocrRepairCard,
  getFastgptConfig,
  saveFastgptConfig,
  type FieldResult,
  type FastgptConfig,
  type StepFastgptConfig,
} from '../api'

const STEPS = [
  { key: 'repair_order_ocr' as keyof FastgptConfig, title: '调修单 OCR 识别', description: '维修器材调修单扫描件识别', icon: <ScanOutlined />, color: '#3378ff' },
  { key: 'repair_card_ocr' as keyof FastgptConfig,  title: '返修卡 OCR 识别', description: '返修件返修卡扫描件识别',   icon: <FileSearchOutlined />, color: '#00d4aa' },
  { key: 'ids_match' as keyof FastgptConfig,        title: 'IDS 系统匹配',   description: '与 IDS 系统数据进行信息匹配', icon: <ApiOutlined />, color: '#f0a020' },
  { key: 'quote_generation' as keyof FastgptConfig, title: '报价数据生成',   description: '汇总识别结果，生成报价单',    icon: <DollarOutlined />, color: '#a855f7' },
]

interface StepState {
  status:  'idle' | 'processing' | 'done' | 'error'
  files:   File[]
  results: FieldResult[]
  info:    string
}
const initState = (): StepState => ({ status: 'idle', files: [], results: [], info: '' })

const EMPTY_FGPT: StepFastgptConfig = { api_url: '', api_key: '', appid: '', enabled: false }
const DEFAULT_CFG: FastgptConfig = {
  repair_order_ocr: { ...EMPTY_FGPT },
  repair_card_ocr:  { ...EMPTY_FGPT },
  ids_match:        { ...EMPTY_FGPT },
  quote_generation: { ...EMPTY_FGPT },
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

  const handleProcess = async (idx: number) => {
    if (idx === 2 || idx === 3) {
      updateStep(idx, { status: 'processing' })
      await new Promise((r) => setTimeout(r, 1200))
      updateStep(idx, { status: 'done', results: idx === 2 ? IDS_MOCK : QUOTE_MOCK, info: '' })
      return
    }
    const state = stepStates[idx]
    if (state.files.length === 0) { messageApi.warning('请先上传图片文件'); return }
    updateStep(idx, { status: 'processing' })
    const sc = fgptCfg[STEPS[idx].key]
    const opts = sc.enabled
      ? { useFastgpt: true, apiUrl: sc.api_url, apiKey: sc.api_key, appid: sc.appid }
      : { useFastgpt: false }
    try {
      const resp = idx === 0
        ? await ocrRepairOrder(state.files[0], opts)
        : await ocrRepairCard(state.files[0], opts)
      updateStep(idx, { status: 'done', results: resp.fields, info: `识别 ${resp.ocr_count} 个文本块 · ${resp.timestamp}` })
      messageApi.success(`步骤 ${idx + 1} 识别完成`)
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e)
      updateStep(idx, { status: 'error', info: msg })
      messageApi.error(`识别失败：${msg}`)
    }
  }

  const step  = STEPS[current]
  const state = stepStates[current]
  const sc    = fgptCfg[step.key]

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
            <h1 style={{ margin: 0, fontSize: 24, fontWeight: 700, color: '#e6edf3' }}>返修件报价智能链路</h1>
            <p style={{ margin: 0, color: '#7d8590', fontSize: 13 }}>按步骤完成各阶段识别，最终生成报价数据</p>
          </div>
        </div>
      </motion.div>

      {/* Steps 导航条 */}
      <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: 0.15 }}
        style={{ background: '#161b22', border: '1px solid #21262d', borderRadius: 14, padding: '28px 32px', marginBottom: 32 }}>
        <Steps current={current} items={antStepItems}
          onChange={(i) => { if (stepStates[i].status === 'done' || i <= current) setCurrent(i) }} />
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
                {sc.enabled && (
                  <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4, background: 'rgba(0,212,170,0.1)', border: '1px solid rgba(0,212,170,0.3)', borderRadius: 20, padding: '2px 10px', fontSize: 11, color: '#00d4aa', fontWeight: 600 }}>
                    <ThunderboltOutlined style={{ fontSize: 10 }} /> FastGPT 已启用
                  </span>
                )}
                <Tag style={{ background: `${step.color}18`, border: `1px solid ${step.color}40`, color: step.color, fontFamily: "'JetBrains Mono', monospace", fontSize: 11 }}>
                  {state.status === 'done' ? '✓ 已完成' : state.status === 'processing' ? '处理中' : state.status === 'error' ? '✗ 失败' : '待处理'}
                </Tag>
                {/* 配置按钮 */}
                <Button
                  size="small"
                  icon={<SettingOutlined />}
                  onClick={() => setShowCfg((prev) => prev.map((v, i) => (i === current ? !v : v)))}
                  style={{ background: showCfg[current] ? `${step.color}20` : '#21262d', borderColor: showCfg[current] ? step.color : '#30363d', color: showCfg[current] ? step.color : '#7d8590', fontSize: 12 }}
                >
                  {cfgLoading ? '加载中...' : 'FastGPT 配置'}
                </Button>
              </div>
            </div>

            {/* FastGPT 配置面板（可折叠） */}
            <AnimatePresence>
              {showCfg[current] && (
                <motion.div initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: 'auto' }} exit={{ opacity: 0, height: 0 }} transition={{ duration: 0.2 }} style={{ overflow: 'hidden' }}>
                  <FgptPanel stepKey={step.key} cfg={fgptCfg} saving={saving} onChange={patchFgpt} onSave={handleSaveCfg} />
                </motion.div>
              )}
            </AnimatePresence>

            {/* 上传区 — 仅步骤0、1显示 */}
            {current < 2 && (
              <div className="mb-6">
                <div style={{ color: '#7d8590', fontSize: 13, marginBottom: 10 }}>上传扫描件图片</div>
                <UploadZone onFiles={(files) => updateStep(current, { files, status: 'idle', results: [] })} multiple={false} />
              </div>
            )}

            {/* IDS 步骤提示 */}
            {current === 2 && state.status !== 'done' && (
              <div style={{ padding: 24, borderRadius: 10, background: '#1c2128', border: '1px solid #21262d', marginBottom: 24, textAlign: 'center' }}>
                <ApiOutlined style={{ fontSize: 36, color: '#f0a020', display: 'block', marginBottom: 12 }} />
                <p style={{ color: '#7d8590', margin: 0 }}>将调用 IDS 系统 API 进行数据匹配</p>
                <p style={{ color: '#484f58', fontSize: 12, margin: '4px 0 0' }}>需要前两步骤均已完成</p>
              </div>
            )}

            {/* 报价生成提示 */}
            {current === 3 && state.status !== 'done' && (
              <div style={{ padding: 24, borderRadius: 10, background: '#1c2128', border: '1px solid #21262d', marginBottom: 24, textAlign: 'center' }}>
                <DollarOutlined style={{ fontSize: 36, color: '#a855f7', display: 'block', marginBottom: 12 }} />
                <p style={{ color: '#7d8590', margin: 0 }}>将汇总所有步骤数据，自动生成报价单</p>
              </div>
            )}

            {/* 操作按钮 */}
            <div className="flex gap-3 mb-6">
              <Button
                type="primary"
                icon={<PlayCircleOutlined />}
                loading={state.status === 'processing'}
                disabled={current < 2 && state.files.length === 0}
                onClick={() => handleProcess(current)}
                style={{ background: step.color, borderColor: step.color, boxShadow: `0 4px 14px ${step.color}50` }}
              >
                {state.status === 'processing' ? '识别中...' : '开始处理'}
              </Button>
              {state.status === 'done' && current < STEPS.length - 1 && (
                <Button onClick={() => setCurrent(current + 1)}
                  style={{ background: '#1c2128', borderColor: '#30363d', color: '#e6edf3' }}>
                  下一步 →
                </Button>
              )}
            </div>

            {/* 识别结果 */}
            <AnimatePresence>
              {state.status === 'done' && state.results.length > 0 && (
                <motion.div initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: 'auto' }} exit={{ opacity: 0, height: 0 }}>
                  <Divider style={{ borderColor: '#21262d', margin: '0 0 16px' }} />
                  {state.info && <p style={{ color: '#7d8590', fontSize: 12, marginBottom: 12 }}>{state.info}</p>}
                  <ResultTable data={state.results} onExport={() => {}} />
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

