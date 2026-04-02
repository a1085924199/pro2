import { useState, useCallback } from 'react'
import { useDropzone } from 'react-dropzone'
import { motion, AnimatePresence } from 'framer-motion'
import { CloudUploadOutlined, FileImageOutlined, CloseCircleOutlined } from '@ant-design/icons'

interface UploadZoneProps {
  onFiles: (files: File[]) => void
  accept?: Record<string, string[]>
  multiple?: boolean
  label?: string
  hint?: string
}

export default function UploadZone({
  onFiles,
  accept = { 'image/*': ['.png', '.jpg', '.jpeg', '.bmp', '.tiff'] },
  multiple = true,
  label = '拖拽图片至此，或点击选择文件',
  hint = '支持 PNG、JPG、BMP、TIFF 格式',
}: UploadZoneProps) {
  const [files, setFiles] = useState<File[]>([])

  const onDrop = useCallback(
    (accepted: File[]) => {
      setFiles(accepted)
      onFiles(accepted)
    },
    [onFiles],
  )

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept,
    multiple,
  })

  const removeFile = (idx: number) => {
    const next = files.filter((_, i) => i !== idx)
    setFiles(next)
    onFiles(next)
  }

  return (
    <div className="flex flex-col gap-3">
      <div
        {...getRootProps()}
        style={{
          border: `2px dashed ${isDragActive ? '#3378ff' : '#30363d'}`,
          borderRadius: 12,
          padding: '40px 20px',
          textAlign: 'center',
          cursor: 'pointer',
          background: isDragActive ? 'rgba(51,120,255,0.06)' : '#161b22',
          transition: 'all 0.2s, border-color 0.2s, background 0.2s, transform 0.15s',
          position: 'relative',
          overflow: 'hidden',
        }}
      >
        <input {...getInputProps()} />

        {/* Animated glow on drag */}
        <AnimatePresence>
          {isDragActive && (
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              style={{
                position: 'absolute',
                inset: 0,
                background: 'radial-gradient(ellipse at center, rgba(51,120,255,0.15) 0%, transparent 70%)',
                pointerEvents: 'none',
              }}
            />
          )}
        </AnimatePresence>

        <motion.div
          animate={{ y: isDragActive ? -6 : 0 }}
          transition={{ type: 'spring', stiffness: 300 }}
        >
          <CloudUploadOutlined
            style={{
              fontSize: 48,
              color: isDragActive ? '#3378ff' : '#484f58',
              display: 'block',
              marginBottom: 12,
              transition: 'color 0.2s',
            }}
          />
          <p style={{ color: isDragActive ? '#3378ff' : '#7d8590', fontSize: 15, margin: 0, fontWeight: 500 }}>
            {isDragActive ? '释放以上传文件' : label}
          </p>
          <p style={{ color: '#484f58', fontSize: 13, margin: '6px 0 0' }}>{hint}</p>
        </motion.div>
      </div>

      {/* File list */}
      <AnimatePresence>
        {files.length > 0 && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: 'auto' }}
            exit={{ opacity: 0, height: 0 }}
            className="flex flex-col gap-2"
          >
            {files.map((f, i) => (
              <motion.div
                key={f.name + i}
                initial={{ opacity: 0, x: -10 }}
                animate={{ opacity: 1, x: 0 }}
                exit={{ opacity: 0, x: 10 }}
                transition={{ delay: i * 0.05 }}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 10,
                  padding: '8px 14px',
                  borderRadius: 8,
                  background: '#1c2128',
                  border: '1px solid #21262d',
                }}
              >
                <FileImageOutlined style={{ color: '#3378ff', fontSize: 16 }} />
                <span style={{ flex: 1, color: '#e6edf3', fontSize: 13, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {f.name}
                </span>
                <span style={{ color: '#484f58', fontSize: 12, whiteSpace: 'nowrap' }}>
                  {(f.size / 1024).toFixed(0)} KB
                </span>
                <CloseCircleOutlined
                  style={{ color: '#484f58', cursor: 'pointer', fontSize: 15 }}
                  onClick={() => removeFile(i)}
                />
              </motion.div>
            ))}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}
