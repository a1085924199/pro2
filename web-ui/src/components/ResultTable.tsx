import { Table, Tag, Button } from 'antd'
import { DownloadOutlined, CopyOutlined } from '@ant-design/icons'
import { motion } from 'framer-motion'
import type { ColumnType } from 'antd/es/table'

export interface FieldResult {
  key: string
  field: string
  value: string
  confidence: number
}

interface ResultTableProps {
  data: FieldResult[]
  onExport?: () => void
  loading?: boolean
}

export default function ResultTable({ data, onExport, loading }: ResultTableProps) {
  const columns: ColumnType<FieldResult>[] = [
    {
      title: '字段名称',
      dataIndex: 'field',
      key: 'field',
      width: 180,
      render: (v: string) => (
        <span style={{ color: '#7d8590', fontFamily: "'JetBrains Mono', monospace", fontSize: 13 }}>{v}</span>
      ),
    },
    {
      title: '识别结果',
      dataIndex: 'value',
      key: 'value',
      render: (v: string) => (
        <span style={{ color: '#e6edf3', fontWeight: 500 }}>{v || <span style={{ color: '#484f58' }}>—</span>}</span>
      ),
    },
    {
      title: '置信度',
      dataIndex: 'confidence',
      key: 'confidence',
      width: 120,
      render: (v: number) => {
        const pct = Math.round(v * 100)
        const color = pct >= 90 ? '#00d4aa' : pct >= 70 ? '#f0a020' : '#ff4d4f'
        return (
          <Tag
            style={{
              background: `${color}18`,
              border: `1px solid ${color}40`,
              color,
              fontFamily: "'JetBrains Mono', monospace",
              fontSize: 12,
            }}
          >
            {pct}%
          </Tag>
        )
      },
    },
    {
      title: '操作',
      key: 'action',
      width: 80,
      render: (_: unknown, record: FieldResult) => (
        <CopyOutlined
          style={{ color: '#484f58', cursor: 'pointer', fontSize: 14 }}
          onClick={() => navigator.clipboard.writeText(record.value)}
        />
      ),
    },
  ]

  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3 }}
    >
      <div className="flex justify-between items-center mb-3">
        <span style={{ color: '#7d8590', fontSize: 13 }}>
          共 <span style={{ color: '#3378ff', fontWeight: 600 }}>{data.length}</span> 个字段
        </span>
        {onExport && (
          <Button
            size="small"
            icon={<DownloadOutlined />}
            onClick={onExport}
            style={{
              background: '#1c2128',
              borderColor: '#30363d',
              color: '#e6edf3',
            }}
          >
            导出 Excel
          </Button>
        )}
      </div>
      <Table
        dataSource={data}
        columns={columns}
        loading={loading}
        pagination={false}
        size="small"
        style={{ borderRadius: 10, overflow: 'hidden' }}
      />
    </motion.div>
  )
}
