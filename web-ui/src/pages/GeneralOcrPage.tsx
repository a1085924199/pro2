import { useState } from 'react'
import { Tabs, Button, Tag, Divider, message, Dropdown } from 'antd'
import {
  FileTextOutlined,
  TableOutlined,
  PlayCircleOutlined,
  CheckCircleFilled,
  FileExcelOutlined,
  FileMarkdownOutlined,
  DownloadOutlined,
  CloudOutlined,
} from '@ant-design/icons'
import { motion, AnimatePresence } from 'framer-motion'
import UploadZone from '../components/UploadZone'
import ResultTable from '../components/ResultTable'
import { ocrGeneral, ocrExportFormat, type FieldResult, downloadExportFile } from '../api'

interface PanelState {
  files:       File[]
  status:      'idle' | 'processing' | 'done' | 'error'
  results:     FieldResult[]
  rawText:     string
  tableHtml:   string
  exports:     Record<string, string> | undefined
  cachedCells: Array<{row: number; col: number; text: string; confidence: number}>
  cachedRows:  number
  cachedCols:  number
}

function initPanel(): PanelState {
  return {
    files: [],
    status: 'idle',
    results: [],
    rawText: '',
    tableHtml: '',
    exports: undefined,
    cachedCells: [],
    cachedRows: 0,
    cachedCols: 0,
  }
}

// 表格 HTML 渲染组件
function HtmlTableView({ html }: { html: string }) {
  const styled = `
    <style>
      table {
        border-collapse: collapse;
        width: 100%;
        font-family: 'Microsoft YaHei', 'PingFang SC', sans-serif;
        font-size: 13px;
        color: #e6edf3;
      }
      th, td {
        border: 1px solid #30363d;
        padding: 8px 12px;
        text-align: left;
        vertical-align: middle;
        min-width: 60px;
        word-break: break-all;
      }
      th {
        background: #21262d;
        font-weight: 700;
        color: #3378ff;
      }
      tr:nth-child(even) td {
        background: rgba(255,255,255,0.03);
      }
      tr:hover td {
        background: rgba(51,120,255,0.08);
      }
    </style>
    ${html}
  `
  if (!html) {
    return (
      <div style={{ padding: '32px', textAlign: 'center', color: '#484f58', fontSize: 14 }}>
        未检测到表格结构，请尝试其他图片
      </div>
    )
  }
  return (
    <div
      style={{
        overflowX: 'auto',
        borderRadius: 8,
        border: '1px solid #21262d',
        background: '#0d1117',
        padding: '4px',
      }}
      dangerouslySetInnerHTML={{ __html: styled }}
    />
  )
}

export default function GeneralOcrPage() {
  const [activeTab, setActiveTab] = useState('doc')
  const [messageApi, contextHolder] = message.useMessage()
  const [docState,   setDocState]   = useState<PanelState>(initPanel())
  const [tableState, setTableState] = useState<PanelState>(initPanel())

  const isDoc   = activeTab === 'doc'
  const state   = isDoc ? docState : tableState
  const setState = (patch: Partial<PanelState>) => {
    if (isDoc) setDocState((p) => ({ ...p, ...patch }))
    else       setTableState((p) => ({ ...p, ...patch }))
  }

  const handleProcess = async (exportFormat: 'none' | 'excel' | 'csv' | 'markdown' | 'html' | 'json' | 'all' = 'none') => {
    if (state.files.length === 0) { messageApi.warning('请先上传图片文件'); return }
    setState({ status: 'processing' })
    try {
      const resp = await ocrGeneral(state.files[0], isDoc ? 'doc' : 'table', exportFormat)
      setState({
        status:      'done',
        results:     resp.fields,
        rawText:     resp.raw_text ?? `已识别 ${resp.ocr_count} 个文本块`,
        tableHtml:   resp.table_html ?? '',
        exports:     resp.exports,
        cachedCells: resp.cells ?? [],
        cachedRows:  resp.num_rows ?? 0,
        cachedCols:  resp.num_cols ?? 0,
      })
      messageApi.success('识别完成')
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e)
      setState({ status: 'error', rawText: msg })
      messageApi.error(`识别失败：${msg}`)
    }
  }

  // 导出单个格式（已有缓存则直接导出，无缓存则走识别路径）
  const handleExport = async (fmt: 'excel' | 'csv' | 'markdown' | 'html' | 'json') => {
    if (state.files.length === 0) { messageApi.warning('请先上传图片文件'); return }
    setState({ status: 'processing' })
    try {
      let filePath: string | undefined
      let resp: Awaited<ReturnType<typeof ocrGeneral>> | null = null

      if (state.cachedCells.length > 0 && state.cachedRows > 0 && state.cachedCols > 0) {
        // 已有识别结果 → 调用专用导出接口，不重跑 OCR
        const exportResp = await ocrExportFormat(state.cachedCells, state.cachedRows, state.cachedCols, fmt)
        filePath = exportResp.exports?.[fmt]
      } else {
        // 无缓存 → 降级走旧的完整识别路径
        resp = await ocrGeneral(state.files[0], isDoc ? 'doc' : 'table', fmt)
        filePath = resp.exports?.[fmt]
      }

      if (filePath) {
        const filename = filePath.split(/[\\/]/).pop() || `${fmt}_export`
        downloadExportFile(filename)
        messageApi.success(`已导出 ${fmt.toUpperCase()} 文件`)
      } else {
        messageApi.warning(`未能获取 ${fmt.toUpperCase()} 文件路径`)
      }

      // 如果走了识别路径，同步更新缓存
      if (resp) {
        const patch: Partial<PanelState> = {
          status:      'done',
          results:     resp.fields,
          rawText:     resp.raw_text ?? '',
          tableHtml:   resp.table_html ?? '',
          exports:     resp.exports,
          cachedCells: resp.cells ?? [],
          cachedRows:  resp.num_rows ?? 0,
          cachedCols:  resp.num_cols ?? 0,
        }
        setState(patch)
      } else {
        setState({ status: 'done' })
      }
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e)
      setState({ status: 'error', rawText: msg })
      messageApi.error(`导出失败：${msg}`)
    }
  }

  // 导出全部格式（已有缓存则直接导出，无缓存则先识别）
  const handleExportAll = async () => {
    if (state.files.length === 0) { messageApi.warning('请先上传图片文件'); return }
    setState({ status: 'processing' })
    try {
      if (state.cachedCells.length > 0 && state.cachedRows > 0 && state.cachedCols > 0) {
        // 有缓存 → 调用导出接口
        const exportResp = await ocrExportFormat(state.cachedCells, state.cachedRows, state.cachedCols, 'all')
        const exports = exportResp.exports ?? {}
        if (Object.keys(exports).length > 0) {
          // 依次触发下载
          for (const [, filePath] of Object.entries(exports)) {
            const filename = filePath.split(/[\\/]/).pop() || 'export'
            downloadExportFile(filename)
            await new Promise((r) => setTimeout(r, 300))
          }
          messageApi.success('已导出全部格式文件')
        } else {
          messageApi.warning('未能获取导出文件路径')
        }
      } else {
        // 无缓存 → 走完整识别 + 导出路径
        await handleProcess('all')
        return
      }
      setState({ status: 'done' })
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e)
      // 导出失败时降级到完整识别路径
      messageApi.warning(`专用导出失败，改为识别后导出：${msg}`)
      await handleProcess('all')
    }
  }

  const color = isDoc ? '#a855f7' : '#3378ff'

  const tabItems = [
    {
      key: 'doc',
      label: (
        <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <FileTextOutlined /> 文档识别
          {docState.status === 'done' && <CheckCircleFilled style={{ color: '#00d4aa', fontSize: 12 }} />}
        </span>
      ),
    },
    {
      key: 'table',
      label: (
        <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <TableOutlined /> 表格识别
          {tableState.status === 'done' && <CheckCircleFilled style={{ color: '#00d4aa', fontSize: 12 }} />}
        </span>
      ),
    },
  ]

  return (
    <div style={{ padding: '40px 24px', maxWidth: 1100, margin: '0 auto' }}>
      {contextHolder}

      {/* 页头 */}
      <motion.div initial={{ opacity: 0, y: -16 }} animate={{ opacity: 1, y: 0 }} className="mb-8">
        <div className="flex items-center gap-3 mb-2">
          <div style={{
            width: 40, height: 40, borderRadius: 10,
            background: 'linear-gradient(135deg, #7c3aed, #a855f7)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            color: '#fff', fontSize: 18,
            boxShadow: '0 4px 16px rgba(168,85,247,0.4)',
          }}>
            <FileTextOutlined />
          </div>
          <div>
            <h1 style={{ margin: 0, fontSize: 24, fontWeight: 700, color: '#e6edf3' }}>通用纸质材料识别</h1>
            <p style={{ margin: 0, color: '#7d8590', fontSize: 13 }}>支持通用文档及表格的 OCR 识别与结构化提取</p>
          </div>
        </div>
      </motion.div>

      {/* 内容卡片 */}
      <motion.div
        initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.15 }}
        style={{ background: '#161b22', border: '1px solid #21262d', borderRadius: 14, padding: 24 }}
      >
        <Tabs activeKey={activeTab} onChange={(k) => setActiveTab(k)} items={tabItems} size="large" />

        <AnimatePresence mode="wait">
          <motion.div
            key={activeTab}
            initial={{ opacity: 0, x: 20 }} animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: -20 }} transition={{ duration: 0.25 }}
          >
            {/* 彩色强调线 */}
            <div style={{ height: 2, background: `linear-gradient(90deg, ${color}, transparent)`, borderRadius: 2, marginBottom: 24 }} />

            <UploadZone
              onFiles={(files) => setState({ files, status: 'idle', results: [], tableHtml: '', exports: undefined, cachedCells: [], cachedRows: 0, cachedCols: 0 })}
              multiple={false}
              label={isDoc ? '拖拽文档图片至此，或点击选择' : '拖拽表格图片至此，或点击选择'}
              hint={isDoc ? '支持扫描件、拍照件等各类文档图片' : '支持印刷表格、手写表格、复杂嵌套表格'}
            />

            <div className="flex gap-3 mt-6 mb-4 items-center flex-wrap">
              <Button
                type="primary"
                icon={<PlayCircleOutlined />}
                loading={state.status === 'processing'}
                disabled={state.files.length === 0}
                onClick={() => handleProcess()}
                style={{ background: color, borderColor: color, boxShadow: `0 4px 14px ${color}50` }}
              >
                {state.status === 'processing' ? '识别中...' : '开始识别'}
              </Button>
              {/* 导出按钮组：仅表格模式显示 */}
              {!isDoc && state.status === 'done' && (
                <div className="flex gap-2">
                  <Dropdown
                    menu={{
                      items: [
                        {
                          key: 'json',
                          icon: <CloudOutlined />,
                          label: '导出 JSON (.json)',
                          onClick: () => handleExport('json'),
                        },
                        {
                          key: 'excel',
                          icon: <FileExcelOutlined />,
                          label: '导出 Excel (.xlsx)',
                          onClick: () => handleExport('excel'),
                        },
                        {
                          key: 'csv',
                          icon: <FileTextOutlined />,
                          label: '导出 CSV (.csv)',
                          onClick: () => handleExport('csv'),
                        },
                        {
                          key: 'html',
                          icon: <FileTextOutlined />,
                          label: '导出 HTML (.html)',
                          onClick: () => handleExport('html'),
                        },
                        {
                          key: 'markdown',
                          icon: <FileMarkdownOutlined />,
                          label: '导出 Markdown (.md)',
                          onClick: () => handleExport('markdown'),
                        },
                        { type: 'divider' },
                        {
                          key: 'all',
                          icon: <DownloadOutlined />,
                          label: '导出全部格式',
                          onClick: () => handleExportAll(),
                        },
                      ],
                    }}
                    trigger={['click']}
                    placement="bottomLeft"
                  >
                    <Button icon={<DownloadOutlined />} style={{ background: '#1f883d', borderColor: '#1f883d' }}>
                      导出结果
                    </Button>
                  </Dropdown>
                </div>
              )}
              {state.status === 'done' && (
                <Tag style={{ background: 'rgba(0,212,170,0.1)', border: '1px solid rgba(0,212,170,0.3)', color: '#00d4aa', padding: '4px 12px', borderRadius: 6, display: 'flex', alignItems: 'center', gap: 4 }}>
                  <CheckCircleFilled /> 识别完成
                </Tag>
              )}
              {state.status === 'error' && (
                <Tag style={{ background: 'rgba(201,42,42,0.1)', border: '1px solid rgba(201,42,42,0.3)', color: '#ff6b6b', padding: '4px 12px', borderRadius: 6 }}>
                  ✗ 识别失败
                </Tag>
              )}
            </div>

            <AnimatePresence>
              {state.status === 'done' && (
                <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }}>
                  <Divider style={{ borderColor: '#21262d' }} />

                  {/* 识别摘要 */}
                  {state.rawText && (
                    <div style={{ marginBottom: 20 }}>
                      <p style={{ color: '#7d8590', fontSize: 12, marginBottom: 8, fontWeight: 600 }}>识别摘要</p>
                      <div style={{ padding: '10px 14px', borderRadius: 8, background: '#1c2128', border: '1px solid #21262d', color: '#e6edf3', fontSize: 13, fontFamily: "'JetBrains Mono', monospace" }}>
                        {state.rawText}
                      </div>
                    </div>
                  )}

                  {/* 表格模式：渲染 HTML 表格 */}
                  {!isDoc && (
                    <div>
                      <p style={{ color: '#7d8590', fontSize: 12, marginBottom: 8, fontWeight: 600 }}>表格预览</p>
                      <HtmlTableView html={state.tableHtml} />
                    </div>
                  )}

                  {/* 文档模式：渲染文本行列表 */}
                  {isDoc && state.results.length > 0 && (
                    <div style={{ marginTop: 20 }}>
                      <p style={{ color: '#7d8590', fontSize: 12, marginBottom: 8, fontWeight: 600 }}>识别文本（共 {state.results.length} 行）</p>
                      <ResultTable data={state.results} onExport={() => {}} />
                    </div>
                  )}
                </motion.div>
              )}
            </AnimatePresence>
          </motion.div>
        </AnimatePresence>
      </motion.div>
    </div>
  )
}
