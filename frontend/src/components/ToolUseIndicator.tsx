/**
 * 工具调用状态指示器
 * RAG 命中时显示 "🧠 想到一个…"，实时搜索时显示 "🔍 找一下…"
 * TODO: 根据 tool 类型和 status 渲染不同状态
 */
interface Props {
  tool: string
  status: 'searching' | 'done'
  source?: string
}

export default function ToolUseIndicator({ tool, status, source }: Props) {
  const isSearch = tool === 'lookup' && source !== 'rag'
  const icon = isSearch ? '🔍' : '🧠'
  const text =
    status === 'searching'
      ? isSearch ? '找一下…' : '想到一个…'
      : isSearch ? '查到了' : '找到了'

  return (
    <div className="flex items-center gap-1.5 text-xs text-sage-600 px-2 py-1.5 my-1">
      <span>{icon}</span>
      <span className="italic">{text}</span>
      {status === 'searching' && (
        <span className="flex gap-0.5 ml-0.5">
          <span className="w-1 h-1 rounded-full bg-sage-400 animate-bounce [animation-delay:0ms]" />
          <span className="w-1 h-1 rounded-full bg-sage-400 animate-bounce [animation-delay:150ms]" />
          <span className="w-1 h-1 rounded-full bg-sage-400 animate-bounce [animation-delay:300ms]" />
        </span>
      )}
    </div>
  )
}
