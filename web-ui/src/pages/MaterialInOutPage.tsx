import { useState } from 'react'
import { Tabs, Button, Tag, Divider, message } from 'antd'
import {
  ExportOutlined,
  ImportOutlined,
  PlayCircleOutlined,
  CheckCircleFilled,
} from '@ant-design/icons'
import { motion, AnimatePresence } from 'framer-motion'
import UploadZone from '../components/UploadZone'
import ResultTable from '../components/ResultTable'
import { ocrMaterial, type FieldResult } from '../api'

const TABS = [
  {
    key: 'out',
    label: '航材出库单识别',
    icon: <ExportOutlined />,
    color: '#00d4aa',
    gradient: 'linear-gradient(135deg, #0f7a5a, #00a884)',
  },
  {
    key: 'in',
    label: '航材入库单识别',
    icon: <ImportOutlined />,
    color: '#3378ff',
    gradient: 'linear-gradient(135deg, #1a57f5, #3378ff)',
  },
]

interface TabState {
  files: File[]
  status: 'idle' | 'processing' | 'done' | 'error'
  results: FieldResult[]
  info: string
}

export default function MaterialInOutPage() {
  const [activeTab, setActiveTab] = useState('out')
  const [messageApi, contextHolder] = message.useMessage()
  const [states, setStates] = useState<Record<string, TabState>>({
    out: { files: [], status: 'idle', results: [], info: '' },
    in:  { files: [], status: 'idle', results: [], info: '' },
  })

  const update = (key: string, patch: Partial<TabState>) =>
    setStates((prev) => ({ ...prev, [key]: { ...prev[key], ...patch } }))

  const handleProcess = async (tabKey: string) => {
    const state = states[tabKey]
    if (state.files.length === 0) { messageApi.warning('请先上传图片文件'); return }
    update(tabKey, { status: 'processing' })
    try {
      const resp = await ocrMaterial(state.files[0], tabKey as 'out' | 'in')
      update(tabKey, { status: 'done', results: resp.fields, info: `识别 ${resp.ocr_count} 个文本块 · ${resp.timestamp}` })
      messageApi.success('识别完成')
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e)
      update(tabKey, { status: 'error', info: msg })
      messageApi.error(`识别失败：${msg}`)
    }
  }

  const tabItems = TABS.map((tab) => ({
    key: tab.key,
    label: (
      <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
        {tab.icon}
        {tab.label}
        {states[tab.key].status === 'done' && (
          <CheckCircleFilled style={{ color: '#00d4aa', fontSize: 12 }} />
        )}
      </span>
    ),
    children: (
      <TabContent
        tab={tab}
        state={states[tab.key]}
        onFiles={(files) => update(tab.key, { files, status: 'idle' })}
        onProcess={() => handleProcess(tab.key)}
      />
    ),
  }))

  return (
    <div style={{ padding: '40px 24px', maxWidth: 1000, margin: '0 auto' }}>
      {contextHolder}
      {/* Header */}
      <motion.div initial={{ opacity: 0, y: -16 }} animate={{ opacity: 1, y: 0 }} className="mb-8">
        <div className="flex items-center gap-3 mb-2">
          <div style={{
            width: 40, height: 40, borderRadius: 10,
            background: 'linear-gradient(135deg, #0f7a5a, #00d4aa)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            color: '#fff', fontSize: 18,
            boxShadow: '0 4px 16px rgba(0,212,170,0.4)',
          }}>
            <ImportOutlined />
          </div>
          <div>
            <h1 style={{ margin: 0, fontSize: 24, fontWeight: 700, color: '#e6edf3' }}>
              航材出入库整理智能链路
            </h1>
            <p style={{ margin: 0, color: '#7d8590', fontSize: 13 }}>
              识别航材出入库单据，自动结构化提取字段数据
            </p>
          </div>
        </div>
      </motion.div>

      {/* Tabs */}
      <motion.div
        initial={{ opacity: 0, y: 16 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.15 }}
        style={{ background: '#161b22', border: '1px solid #21262d', borderRadius: 14, padding: 24 }}
      >
        <Tabs
          activeKey={activeTab}
          onChange={setActiveTab}
          items={tabItems}
          size="large"
        />
      </motion.div>
    </div>
  )
}

interface TabContentProps {
  tab: typeof TABS[0]
  state: TabState
  onFiles: (files: File[]) => void
  onProcess: () => void
}

function TabContent({ tab, state, onFiles, onProcess }: TabContentProps) {
  return (
    <div style={{ paddingTop: 16 }}>
      {/* Color accent */}
      <div style={{
        height: 3,
        background: `linear-gradient(90deg, ${tab.color}, transparent)`,
        borderRadius: 2,
        marginBottom: 24,
      }} />

      <UploadZone
        onFiles={onFiles}
        multiple={false}
        label={`拖拽${tab.label.replace('识别', '')}图片至此`}
      />

      <div className="flex gap-3 mt-6 mb-4">
        <Button
          type="primary"
          icon={<PlayCircleOutlined />}
          loading={state.status === 'processing'}
          disabled={state.files.length === 0}
          onClick={onProcess}
          style={{
            background: tab.color,
            borderColor: tab.color,
            boxShadow: `0 4px 14px ${tab.color}50`,
          }}
        >
          {state.status === 'processing' ? '识别中...' : '开始识别'}
        </Button>
        {state.status === 'done' && (
          <Tag style={{
            background: 'rgba(0,212,170,0.1)',
            border: '1px solid rgba(0,212,170,0.3)',
            color: '#00d4aa',
            padding: '4px 12px',
            borderRadius: 6,
            display: 'flex',
            alignItems: 'center',
            gap: 4,
          }}>
            <CheckCircleFilled /> 识别完成
          </Tag>
        )}
      </div>

      <AnimatePresence>
        {state.status === 'done' && state.results.length > 0 && (
          <motion.div
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0 }}
          >
            <Divider style={{ borderColor: '#21262d' }} />
            <ResultTable data={state.results} onExport={() => {}} />
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}
