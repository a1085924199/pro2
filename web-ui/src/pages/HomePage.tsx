import { useNavigate } from 'react-router-dom'
import { motion } from 'framer-motion'
import {
  ToolOutlined,
  InboxOutlined,
  FileTextOutlined,
  ClockCircleOutlined,
  ArrowRightOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons'

interface ChainCard {
  id: string
  title: string
  subtitle: string
  icon: React.ReactNode
  route: string
  gradient: string
  glowColor: string
  steps: string[]
  available: boolean
  tag?: string
}

const cards: ChainCard[] = [
  {
    id: 'repair',
    title: '地面返修件报价智能链路',
    subtitle: '调修单OCR识别 · 返修卡OCR识别 · 档案生成 · 报价数据生成',
    icon: <ToolOutlined />,
    route: '/return-repair-quote',
    gradient: 'linear-gradient(135deg, #1a57f5 0%, #3378ff 50%, #00d4aa 100%)',
    glowColor: 'rgba(51,120,255,0.4)',
    steps: ['调修单OCR识别', '返修卡OCR识别', '档案生成', '报价数据生成'],
    available: true,
    tag: '5步链路',
  },
  {
    id: 'material',
    title: '航材返修件报价智能链路',
    subtitle: '航材出库单识别 · 航材入库单识别 · 数据整理',
    icon: <InboxOutlined />,
    route: '/material-in-out',
    gradient: 'linear-gradient(135deg, #0f7a5a 0%, #00a884 50%, #4fffd7 100%)',
    glowColor: 'rgba(0,212,170,0.4)',
    steps: ['出库单识别', '入库单识别', '数据汇总'],
    available: true,
    tag: '2功能',
  },
  {
    id: 'ocr',
    title: '通用纸质材料识别',
    subtitle: '文档OCR识别 · 通用表格结构化提取',
    icon: <FileTextOutlined />,
    route: '/general-ocr',
    gradient: 'linear-gradient(135deg, #7c3aed 0%, #a855f7 50%, #e879f9 100%)',
    glowColor: 'rgba(168,85,247,0.4)',
    steps: ['文档识别', '表格识别'],
    available: true,
    tag: '2功能',
  },
  {
    id: 'pending',
    title: '待开发',
    subtitle: '更多智能链路功能即将上线，敬请期待',
    icon: <ClockCircleOutlined />,
    route: '',
    gradient: 'linear-gradient(135deg, #21262d 0%, #30363d 100%)',
    glowColor: 'rgba(255,255,255,0.05)',
    steps: ['规划中...'],
    available: false,
  },
]

const containerVariants = {
  hidden: {},
  visible: {
    transition: { staggerChildren: 0.12, delayChildren: 0.2 },
  },
}

const cardVariants = {
  hidden: { opacity: 0, y: 40, scale: 0.96 },
  visible: { opacity: 1, y: 0, scale: 1, transition: { duration: 0.5, ease: [0.22, 1, 0.36, 1] as [number,number,number,number] } },
}

export default function HomePage() {
  const navigate = useNavigate()

  return (
    <div
      className="min-h-screen dot-bg"
      style={{ padding: '60px 24px 80px' }}
    >
      {/* Hero */}
      <motion.div
        initial={{ opacity: 0, y: -20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.6 }}
        className="text-center mb-16 max-w-3xl mx-auto"
      >
        {/* Badge */}
        <motion.div
          initial={{ opacity: 0, scale: 0.8 }}
          animate={{ opacity: 1, scale: 1 }}
          transition={{ delay: 0.1, duration: 0.4 }}
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: 6,
            padding: '4px 14px',
            borderRadius: 20,
            border: '1px solid rgba(51,120,255,0.4)',
            background: 'rgba(51,120,255,0.1)',
            marginBottom: 24,
          }}
        >
          <ThunderboltOutlined style={{ color: '#3378ff', fontSize: 12 }} />
          <span style={{ color: '#3378ff', fontSize: 12, fontWeight: 600, letterSpacing: '0.08em' }}>
            AI · POWERED · OCR
          </span>
        </motion.div>

        <h1
          style={{
            fontSize: 'clamp(32px, 5vw, 56px)',
            fontWeight: 700,
            lineHeight: 1.15,
            margin: '0 0 16px',
            background: 'linear-gradient(135deg, #e6edf3 30%, #7d8590)',
            WebkitBackgroundClip: 'text',
            WebkitTextFillColor: 'transparent',
          }}
        >
          智·链  OCR平台
        </h1>

        <p style={{ color: '#7d8590', fontSize: 16, lineHeight: 1.7, margin: 0 }}>
          基于深度学习的文字识别引擎，以链路形式串联多步骤业务流程
          <br />
          从图像上传到结构化数据，一键完成
        </p>
      </motion.div>

      {/* Cards Grid */}
      <motion.div
        variants={containerVariants}
        initial="hidden"
        animate="visible"
        className="max-w-6xl mx-auto grid grid-cols-1 md:grid-cols-2 gap-6"
      >
        {cards.map((card) => (
          <motion.div
            key={card.id}
            variants={cardVariants}
            whileHover={card.available ? { y: -6, scale: 1.01 } : {}}
            whileTap={card.available ? { scale: 0.99 } : {}}
            onClick={() => card.available && navigate(card.route)}
            className="gradient-border"
            style={{
              cursor: card.available ? 'pointer' : 'default',
              borderRadius: 16,
              overflow: 'hidden',
              opacity: card.available ? 1 : 0.6,
            }}
          >
            <div
              style={{
                background: '#161b22',
                border: '1px solid #21262d',
                borderRadius: 16,
                padding: 28,
                height: '100%',
                position: 'relative',
                overflow: 'hidden',
              }}
            >
              {/* Background glow blob */}
              <div
                style={{
                  position: 'absolute',
                  top: -40,
                  right: -40,
                  width: 160,
                  height: 160,
                  borderRadius: '50%',
                  background: card.glowColor,
                  filter: 'blur(50px)',
                  pointerEvents: 'none',
                  opacity: card.available ? 0.6 : 0.2,
                }}
              />

              {/* Header */}
              <div className="flex items-start justify-between mb-5">
                <div
                  style={{
                    width: 52,
                    height: 52,
                    borderRadius: 14,
                    background: card.gradient,
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    fontSize: 22,
                    color: '#fff',
                    flexShrink: 0,
                    boxShadow: `0 8px 24px ${card.glowColor}`,
                  }}
                >
                  {card.icon}
                </div>
                {card.tag && (
                  <span
                    style={{
                      fontSize: 11,
                      fontWeight: 600,
                      padding: '3px 10px',
                      borderRadius: 20,
                      border: '1px solid #30363d',
                      color: '#7d8590',
                      fontFamily: "'JetBrains Mono', monospace",
                      letterSpacing: '0.05em',
                    }}
                  >
                    {card.tag}
                  </span>
                )}
              </div>

              {/* Title */}
              <h2
                style={{
                  fontSize: 20,
                  fontWeight: 700,
                  color: '#e6edf3',
                  margin: '0 0 8px',
                  lineHeight: 1.3,
                }}
              >
                {card.title}
              </h2>
              <p style={{ color: '#7d8590', fontSize: 13, margin: '0 0 20px', lineHeight: 1.6 }}>
                {card.subtitle}
              </p>

              {/* Steps preview */}
              <div className="flex flex-wrap gap-2 mb-5">
                {card.steps.map((step, i) => (
                  <div key={i} className="flex items-center gap-1.5">
                    {i > 0 && (
                      <ArrowRightOutlined style={{ color: '#484f58', fontSize: 10 }} />
                    )}
                    <span
                      style={{
                        fontSize: 12,
                        color: card.available ? '#7d8590' : '#484f58',
                        padding: '3px 10px',
                        borderRadius: 6,
                        background: '#1c2128',
                        border: '1px solid #21262d',
                        whiteSpace: 'nowrap',
                      }}
                    >
                      {step}
                    </span>
                  </div>
                ))}
              </div>

              {/* CTA */}
              {card.available ? (
                <div
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: 6,
                    color: '#3378ff',
                    fontSize: 13,
                    fontWeight: 600,
                  }}
                >
                  进入链路
                  <motion.span
                    animate={{ x: [0, 4, 0] }}
                    transition={{ repeat: Infinity, duration: 1.5 }}
                  >
                    <ArrowRightOutlined style={{ fontSize: 12 }} />
                  </motion.span>
                </div>
              ) : (
                <span style={{ color: '#484f58', fontSize: 13 }}>开发中...</span>
              )}
            </div>
          </motion.div>
        ))}
      </motion.div>

      {/* Bottom decorative line */}
      <motion.div
        initial={{ scaleX: 0, opacity: 0 }}
        animate={{ scaleX: 1, opacity: 1 }}
        transition={{ delay: 0.8, duration: 0.8 }}
        className="max-w-6xl mx-auto mt-16"
        style={{
          height: 1,
          background: 'linear-gradient(90deg, transparent, #21262d, transparent)',
        }}
      />
      <motion.p
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ delay: 1, duration: 0.5 }}
        className="text-center mt-6"
        style={{ color: '#484f58', fontSize: 12, fontFamily: "'JetBrains Mono', monospace" }}
      >
        智·链 OCR 平台 · Powered by PaddleOCR + FastGPT
      </motion.p>
    </div>
  )
}
