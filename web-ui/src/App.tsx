import { BrowserRouter, Routes, Route } from 'react-router-dom'
import Layout from './components/Layout'
import HomePage from './pages/HomePage'
import ReturnRepairPage from './pages/ReturnRepairPage'
import MaterialInOutPage from './pages/MaterialInOutPage'
import GeneralOcrPage from './pages/GeneralOcrPage'

export default function App() {
  return (
    <BrowserRouter>
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
