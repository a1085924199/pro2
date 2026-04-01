import React from 'react'
import ReactDOM from 'react-dom/client'
import { ConfigProvider, theme } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import App from './App'
import './index.css'

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <ConfigProvider
      locale={zhCN}
      theme={{
        algorithm: theme.darkAlgorithm,
        token: {
          colorPrimary: '#3378ff',
          colorSuccess: '#00d4aa',
          colorWarning: '#f0a020',
          colorError: '#ff4d4f',
          colorBgBase: '#0d1117',
          colorBgContainer: '#161b22',
          colorBgElevated: '#1c2128',
          colorBorder: '#21262d',
          colorBorderSecondary: '#30363d',
          colorText: '#e6edf3',
          colorTextSecondary: '#7d8590',
          colorTextTertiary: '#484f58',
          borderRadius: 8,
          fontFamily: "'Noto Sans SC', sans-serif",
        },
        components: {
          Steps: {
            colorPrimary: '#3378ff',
          },
          Card: {
            colorBgContainer: '#161b22',
          },
          Upload: {
            colorBgContainer: '#161b22',
          },
        },
      }}
    >
      <App />
    </ConfigProvider>
  </React.StrictMode>,
)
