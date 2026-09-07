import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import AppointmentSummaryView from './AppointmentSummaryView'
import * as client from '../../api/client'

vi.mock('../../api/client', () => ({
  fetchAppointmentSummary: vi.fn(),
  fetchAppointmentSummaryPdf: vi.fn(),
}))

const RESULT = {
  period: '2026-08-19 ~ 2026-09-02',
  bullets: ['情绪低落/困难的记录主要出现在晚上（4/5 次）', '过去 14 天平均睡眠 5.8 小时，且后半段明显比前半段短'],
  discuss_topics: '注意力下降和持续疲惫',
  generated_at: '2026-09-02T12:00:00Z',
}

// userEvent.setup() 自己会给 navigator.clipboard 装一套真实实现，
// 会覆盖掉提前打好的桩，所以每次都要在 setup() 之后重新打一遍。
let writeTextMock: ReturnType<typeof vi.fn>

function setupUser() {
  const user = userEvent.setup()
  writeTextMock = vi.fn().mockResolvedValue(undefined)
  Object.defineProperty(navigator, 'clipboard', {
    value: { writeText: writeTextMock },
    configurable: true,
  })
  return user
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('AppointmentSummaryView', () => {
  it('defaults to 14 days and lets the user pick a different range', async () => {
    const user = userEvent.setup()
    render(<AppointmentSummaryView />)

    const fourteenDays = screen.getByText('过去 14 天')
    expect(fourteenDays).toHaveClass('border-accent-500')

    await user.click(screen.getByText('过去 30 天'))
    expect(screen.getByText('过去 30 天')).toHaveClass('border-accent-500')
    expect(fourteenDays).not.toHaveClass('border-accent-500')
  })

  it('generates a summary with the selected days and discuss topics', async () => {
    vi.mocked(client.fetchAppointmentSummary).mockResolvedValue(RESULT)
    const user = userEvent.setup()
    render(<AppointmentSummaryView />)

    await user.click(screen.getByText('过去 7 天'))
    await user.type(screen.getByPlaceholderText('比如：注意力下降、持续疲惫'), '注意力下降和持续疲惫')
    await user.click(screen.getByText('生成问诊摘要'))

    expect(client.fetchAppointmentSummary).toHaveBeenCalledWith(7, '注意力下降和持续疲惫')
    expect(await screen.findByText('情绪低落/困难的记录主要出现在晚上（4/5 次）')).toBeInTheDocument()
    expect(screen.getByText('想重点讨论')).toBeInTheDocument() // 结果卡片里的"重点讨论"小节标题
  })

  it('omits discuss_topics from the request when left blank', async () => {
    vi.mocked(client.fetchAppointmentSummary).mockResolvedValue({ ...RESULT, discuss_topics: null })
    const user = userEvent.setup()
    render(<AppointmentSummaryView />)

    await user.click(screen.getByText('生成问诊摘要'))

    expect(client.fetchAppointmentSummary).toHaveBeenCalledWith(14, undefined)
  })

  it('shows an error message when generation fails', async () => {
    vi.mocked(client.fetchAppointmentSummary).mockRejectedValue(new Error('服务暂时出了点问题，请稍后再试'))
    const user = userEvent.setup()
    render(<AppointmentSummaryView />)

    await user.click(screen.getByText('生成问诊摘要'))

    expect(await screen.findByText('服务暂时出了点问题，请稍后再试')).toBeInTheDocument()
  })

  it('copies the formatted summary to the clipboard', async () => {
    vi.mocked(client.fetchAppointmentSummary).mockResolvedValue(RESULT)
    const user = setupUser()
    render(<AppointmentSummaryView />)

    await user.click(screen.getByText('生成问诊摘要'))
    await screen.findByText('问诊摘要')

    await user.click(screen.getByTitle('复制到剪贴板'))

    expect(writeTextMock).toHaveBeenCalledWith(
      expect.stringContaining('情绪低落/困难的记录主要出现在晚上（4/5 次）'),
    )
    expect(writeTextMock).toHaveBeenCalledWith(
      expect.stringContaining('想重点讨论：注意力下降和持续疲惫'),
    )
    expect(await screen.findByTitle('复制到剪贴板')).toBeInTheDocument() // 复制完按钮还在，只是图标换成了对勾
  })

  it('downloads the PDF report with the selected days and discuss topics', async () => {
    vi.mocked(client.fetchAppointmentSummary).mockResolvedValue(RESULT)
    const pdfBlob = new Blob(['fake pdf content'], { type: 'application/pdf' })
    vi.mocked(client.fetchAppointmentSummaryPdf).mockResolvedValue(pdfBlob)

    // jsdom 不实现 URL.createObjectURL/revokeObjectURL，本地打个桩，
    // 顺便验证下载真的走了"生成临时链接→点击→回收"这条路径。
    const createObjectURL = vi.fn().mockReturnValue('blob:fake-url')
    const revokeObjectURL = vi.fn()
    vi.stubGlobal('URL', { ...URL, createObjectURL, revokeObjectURL })
    const clickSpy = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})

    const user = userEvent.setup()
    render(<AppointmentSummaryView />)

    await user.click(screen.getByText('过去 30 天'))
    await user.type(screen.getByPlaceholderText('比如：注意力下降、持续疲惫'), '注意力下降')
    await user.click(screen.getByText('生成问诊摘要'))
    await screen.findByText('问诊摘要')

    await user.click(screen.getByTitle('下载正式报告 PDF'))

    expect(client.fetchAppointmentSummaryPdf).toHaveBeenCalledWith(30, '注意力下降')
    expect(createObjectURL).toHaveBeenCalledWith(pdfBlob)
    expect(clickSpy).toHaveBeenCalled()
    expect(revokeObjectURL).toHaveBeenCalledWith('blob:fake-url')

    clickSpy.mockRestore()
    vi.unstubAllGlobals()
  })

  it('shows an error message when PDF download fails', async () => {
    vi.mocked(client.fetchAppointmentSummary).mockResolvedValue(RESULT)
    vi.mocked(client.fetchAppointmentSummaryPdf).mockRejectedValue(new Error('PDF 生成失败，请稍后再试'))
    const user = userEvent.setup()
    render(<AppointmentSummaryView />)

    await user.click(screen.getByText('生成问诊摘要'))
    await screen.findByText('问诊摘要')

    await user.click(screen.getByTitle('下载正式报告 PDF'))

    expect(await screen.findByText('PDF 生成失败，请稍后再试')).toBeInTheDocument()
  })
})
