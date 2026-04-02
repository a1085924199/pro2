import axios from 'axios'

// 开发时 Vite 代理 /api -> http://localhost:8000
// 生产时同域部署，直接访问
const BASE = '/api'

// 与 vite 代理、server 端口一致（默认 8001，见 web-ui/.env.development 的 VITE_API_PORT）
const API_PORT = import.meta.env.VITE_API_PORT || '8001'
const DOWNLOAD_BASE = `http://127.0.0.1:${API_PORT}/api`

export const api = axios.create({
  baseURL: BASE,
  timeout: 60000, // 普通请求 60s
})

// OCR 专用实例：模型首次加载可能需要数分钟
export const ocrApi = axios.create({
  baseURL: BASE,
  timeout: 600000, // 10 分钟，覆盖模型冷启动场景
})

// ─── 类型定义 ────────────────────────────────────────────────
export interface FieldResult {
  key: string
  field: string
  value: string
  confidence: number
}

export interface OcrResponse {
  success:    boolean
  fields:     FieldResult[]
  ocr_count:  number
  timestamp:  string
  raw_text?:  string
  table_html?: string
  cells?:     Array<{row: number; col: number; text: string; confidence: number}>
  num_rows?:  number
  num_cols?:  number
  exports?:   Record<string, string>
  /** PPStructureV3 原始表格文件路径 */
  raw_exports?: {
    json?: string | null
    html?: string | null
    xlsx?: string | null
  }
  /** FastGPT 是否被用于增强识别 */
  fastgpt_used?: boolean
}

// ─── 健康检查 ────────────────────────────────────────────────
export async function checkHealth(): Promise<{ status: string }> {
  const res = await api.get('/health')
  return res.data
}

// ─── 调修单 OCR ──────────────────────────────────────────────
export async function ocrRepairOrder(
  file: File,
  opts?: { useFastgpt?: boolean; apiUrl?: string; apiKey?: string; appid?: string; fastBatch?: boolean },
): Promise<OcrResponse & { fast_batch?: boolean }> {
  const form = new FormData()
  form.append('file', file)
  form.append('use_fastgpt', String(opts?.useFastgpt ?? false))
  form.append('fast_batch', String(opts?.fastBatch ?? false))
  form.append('api_url',  opts?.apiUrl  ?? '')
  form.append('api_key',  opts?.apiKey  ?? '')
  form.append('appid',    opts?.appid   ?? '')
  const res = await ocrApi.post('/ocr/repair-order', form)
  return res.data
}

/** 调修单批量识别 */
export async function ocrRepairOrderBatch(
  files: File[],
  opts?: { useFastgpt?: boolean; fastBatch?: boolean; apiUrl?: string; apiKey?: string; appid?: string },
): Promise<{
  success: boolean; fast_batch: boolean; count: number
  results: Array<{ success: boolean; filename: string; fields: FieldResult[]; ocr_count: number; timestamp: string; fastgpt_used: boolean; error: string | null }>
}> {
  const form = new FormData()
  for (const f of files) form.append('files', f)
  form.append('use_fastgpt', String(opts?.useFastgpt ?? false))
  form.append('fast_batch', String(opts?.fastBatch ?? true))
  form.append('api_url',  opts?.apiUrl  ?? '')
  form.append('api_key',  opts?.apiKey  ?? '')
  form.append('appid',    opts?.appid   ?? '')
  const res = await ocrApi.post('/ocr/repair-order/batch', form)
  return res.data
}

/** 批量导出调修单 / 返修卡识别结果（多行同一工作表） */
export async function exportRepairBatch(
  rows: Array<{ image_name: string; recognition_time: string; fields: FieldResult[] }>,
  docType: 'repair_order' | 'repair_card',
  fmt: 'excel' | 'csv' | 'json' | 'all' = 'excel',
  images?: File[],
): Promise<{ success: boolean; exports: Record<string, string>; timestamp: string }> {
  const form = new FormData()
  form.append('batch_json', JSON.stringify(rows))
  form.append('doc_type', docType)
  form.append('fmt', fmt)
  if (images) for (const im of images) form.append('images', im)
  const res = await (images ? ocrApi : api).post('/ocr/repair-order/export-batch', form)
  return res.data
}

// ─── 调修单结果导出 ──────────────────────────────────────────
export interface ExportRepairOrderOpts {
  /** repair_order：横向模板 + 原图；repair_card：返修卡横向模板 + 末列原图 */
  docType?: 'repair_order' | 'repair_card'
  /** 原图文件，Excel 嵌入缩略图（调修单 J 列 / 返修卡 N 列） */
  imageFile?: File
  /** 对应「图片名称」列 */
  imageName?: string
  /** 对应「识别时间」列，缺省由后端填当前时间 */
  recognitionTime?: string
}

export async function exportRepairOrder(
  fields: Array<{key: string; field: string; value: string; confidence: number}>,
  fmt: 'excel' | 'csv' | 'json' | 'all' = 'excel',
  opts?: ExportRepairOrderOpts,
): Promise<{ success: boolean; exports: Record<string, string>; timestamp: string }> {
  const form = new FormData()
  form.append('fields_json', JSON.stringify(fields))
  form.append('fmt', fmt)
  form.append('doc_type', opts?.docType ?? 'repair_order')
  if (opts?.imageName) form.append('image_name', opts.imageName)
  if (opts?.recognitionTime) form.append('recognition_time', opts.recognitionTime)
  if (opts?.imageFile) form.append('original_image', opts.imageFile)
  const client = opts?.imageFile ? ocrApi : api
  const res = await client.post('/ocr/repair-order/export', form)
  return res.data
}

// ─── FastGPT 配置 ────────────────────────────────────────────
export interface StepFastgptConfig {
  api_url: string
  api_key: string
  appid: string
  enabled: boolean
}

export interface FastgptConfig {
  repair_order_ocr:  StepFastgptConfig
  repair_card_ocr:   StepFastgptConfig
  archive_generation: StepFastgptConfig
  ids_match:         StepFastgptConfig
  quote_generation:  StepFastgptConfig
}

export async function getFastgptConfig(): Promise<FastgptConfig> {
  const res = await api.get('/config/fastgpt')
  return res.data
}

export async function saveFastgptConfig(cfg: FastgptConfig): Promise<{ success: boolean }> {
  const res = await api.post('/config/fastgpt', cfg)
  return res.data
}

// ─── 返修卡 OCR ──────────────────────────────────────────────
export async function ocrRepairCard(
  file: File,
  opts?: { useFastgpt?: boolean; apiUrl?: string; apiKey?: string; appid?: string; fastBatch?: boolean },
): Promise<OcrResponse & { fast_batch?: boolean }> {
  const form = new FormData()
  form.append('file', file)
  form.append('use_fastgpt', String(opts?.useFastgpt ?? false))
  form.append('fast_batch', String(opts?.fastBatch ?? false))
  form.append('api_url',  opts?.apiUrl  ?? '')
  form.append('api_key',  opts?.apiKey  ?? '')
  form.append('appid',    opts?.appid   ?? '')
  const res = await ocrApi.post('/ocr/repair-card', form)
  return res.data
}

/** 返修卡批量识别 */
export async function ocrRepairCardBatch(
  files: File[],
  opts?: { useFastgpt?: boolean; fastBatch?: boolean; apiUrl?: string; apiKey?: string; appid?: string },
): Promise<{
  success: boolean; fast_batch: boolean; count: number
  results: Array<{ success: boolean; filename: string; fields: FieldResult[]; ocr_count: number; timestamp: string; fastgpt_used: boolean; error: string | null }>
}> {
  const form = new FormData()
  for (const f of files) form.append('files', f)
  form.append('use_fastgpt', String(opts?.useFastgpt ?? false))
  form.append('fast_batch', String(opts?.fastBatch ?? true))
  form.append('api_url',  opts?.apiUrl  ?? '')
  form.append('api_key',  opts?.apiKey  ?? '')
  form.append('appid',    opts?.appid   ?? '')
  const res = await ocrApi.post('/ocr/repair-card/batch', form)
  return res.data
}

// ─── 航材出入库单 OCR ─────────────────────────────────────────
export async function ocrMaterial(
  file: File,
  docType: 'out' | 'in',
): Promise<OcrResponse> {
  const form = new FormData()
  form.append('file', file)
  form.append('doc_type', docType)
  const res = await ocrApi.post('/ocr/material', form)
  return res.data
}

// ─── 通用 OCR ────────────────────────────────────────────────
export async function ocrGeneral(
  file: File,
  mode: 'doc' | 'table',
  exportFormat: 'none' | 'excel' | 'csv' | 'markdown' | 'html' | 'json' | 'all' = 'none',
): Promise<OcrResponse & { exports?: Record<string, string> }> {
  const form = new FormData()
  form.append('file', file)
  form.append('mode', mode)
  form.append('export_format', exportFormat)
  const res = await ocrApi.post('/ocr/general', form)
  return res.data
}

// ─── 专用导出接口（不重跑 OCR，只转换格式）──────────────────────
export async function ocrExportFormat(
  cells:   Array<{row: number; col: number; text: string; confidence: number}>,
  numRows: number,
  numCols: number,
  fmt: 'excel' | 'csv' | 'markdown' | 'html' | 'json' | 'all',
): Promise<{ success: boolean; exports: Record<string, string>; timestamp: string }> {
  const form = new FormData()
  form.append('cells',    JSON.stringify(cells))
  form.append('num_rows', String(numRows))
  form.append('num_cols', String(numCols))
  form.append('fmt',      fmt)
  const res = await api.post('/ocr/export-format', form)
  return res.data
}

// ─── 导出文件下载 ────────────────────────────────────────────
export interface ExportFile {
  name: string
  size: number
  modified: string
}

export async function listExportFiles(): Promise<{ files: ExportFile[] }> {
  const res = await api.get('/export/list')
  return res.data
}

/**
 * 下载指定文件名的导出结果
 * @param filename 后端 output 目录下的文件名
 */
export function downloadExportFile(filename: string): void {
  const url = `${DOWNLOAD_BASE}/export/download?filename=${encodeURIComponent(filename)}`
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
}
