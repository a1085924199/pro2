import { Outlet, useLocation, useNavigate } from 'react-router-dom'
import { motion, AnimatePresence } from 'framer-motion'
import { ArrowLeftOutlined, HomeOutlined, BranchesOutlined } from '@ant-design/icons'

const routeTitles: Record<string, string> = {
  '/': '智能链路 OCR 平台',
  '/return-repair-quote': '地面返修件报价智能链路',
  '/material-in-out': '航材返修件报价智能链路',
  '/general-ocr': '通用纸质材料识别',
}

export default function Layout() {
  const location = useLocation()
  const navigate = useNavigate()
  const isHome = location.pathname === '/'
  const title = routeTitles[location.pathname] ?? '智能链路 OCR 平台'

  return (
    <div className="min-h-screen flex flex-col" style={{ background: '#0d1117' }}>
      {/* Top Nav */}
      <header
        style={{
          background: 'rgba(22,27,34,0.85)',
          backdropFilter: 'blur(16px)',
          borderBottom: '1px solid #21262d',
          position: 'sticky',
          top: 0,
          zIndex: 100,
        }}
      >
        <div className="max-w-7xl mx-auto px-6 py-3 flex items-center gap-4">
          {/* Logo */}
          <div
            className="flex items-center gap-2 cursor-pointer"
            onClick={() => navigate('/')}
          >
            <div
              style={{
                width: 32,
                height: 32,
                borderRadius: 8,
                background: 'linear-gradient(135deg, #3378ff, #00d4aa)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
              }}
            >
              <BranchesOutlined style={{ color: '#fff', fontSize: 16 }} />
            </div>
            <span
              style={{
                fontFamily: "'JetBrains Mono', monospace",
                fontWeight: 700,
                fontSize: 14,
                color: '#e6edf3',
                letterSpacing: '0.05em',
              }}
            >
              OCR<span style={{ color: '#3378ff' }}>·</span>CHAIN
            </span>
          </div>

          {/* Divider */}
          <div style={{ width: 1, height: 20, background: '#30363d' }} />

          {/* Breadcrumb */}
          <AnimatePresence mode="wait">
            <motion.div
              key={location.pathname}
              initial={{ opacity: 0, x: -10 }}
              animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0, x: 10 }}
              transition={{ duration: 0.2 }}
              className="flex items-center gap-2"
            >
              {!isHome && (
                <>
                  <HomeOutlined
                    style={{ color: '#7d8590', fontSize: 13, cursor: 'pointer' }}
                    onClick={() => navigate('/')}
                  />
                  <span style={{ color: '#484f58' }}>/</span>
                </>
              )}
              <span style={{ color: '#e6edf3', fontSize: 14, fontWeight: 500 }}>
                {title}
              </span>
            </motion.div>
          </AnimatePresence>

          <div className="flex-1" />

          {/* Back button */}
          {!isHome && (
            <motion.button
              initial={{ opacity: 0, scale: 0.9 }}
              animate={{ opacity: 1, scale: 1 }}
              onClick={() => navigate('/')}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 6,
                padding: '6px 14px',
                borderRadius: 6,
                border: '1px solid #21262d',
                background: 'transparent',
                color: '#7d8590',
                cursor: 'pointer',
                fontSize: 13,
                transition: 'all 0.2s',
              }}
              whileHover={{ borderColor: '#3378ff', color: '#3378ff', background: 'rgba(51,120,255,0.08)' }}
              whileTap={{ scale: 0.97 }}
            >
              <ArrowLeftOutlined style={{ fontSize: 12 }} />
              返回首页
            </motion.button>
          )}
        </div>
      </header>

      {/* Page Content */}
      <main className="flex-1">
        <AnimatePresence mode="wait">
          <motion.div
            key={location.pathname}
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -20 }}
            transition={{ duration: 0.3, ease: 'easeOut' }}
            style={{ minHeight: 'calc(100vh - 57px)' }}
          >
            <Outlet />
          </motion.div>
        </AnimatePresence>
      </main>
    </div>
  )
}
