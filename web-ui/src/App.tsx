import { BrowserRouter, Routes, Route } from 'react-router-dom'
import Layout from './components/Layout'
import HomePage from './pages/HomePage'
import ReturnRepairPage from './pages/ReturnRepairPage'
import MaterialInOutPage from './pages/MaterialInOutPage'
import GeneralOcrPage from './pages/GeneralOcrPage'

// 生产构建 base 为 /web-ui/，须与路由 basename 一致，否则访问 /web-ui/ 时无路由匹配、只剩深色背景像黑屏
const routerBasename =
  import.meta.env.BASE_URL === '/' ? undefined : import.meta.env.BASE_URL.replace(/\/$/, '')

export default function App() {
  return (
    <BrowserRouter basename={routerBasename}>
      <Routes>
        <Route path="/" element={<Layout />}>
          <Route index element={<HomePage />} />
          <Route path="return-repair-quote" element={<ReturnRepairPage />} />
          <Route path="material-in-out" element={<MaterialInOutPage />} />
          <Route path="general-ocr" element={<GeneralOcrPage />} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}
