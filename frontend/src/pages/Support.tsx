import { useEffect, useState } from 'react'
import { Phone, Plus, Trash2 } from 'lucide-react'
import { COPING_TOOLS, PROFESSIONAL_ORGS } from '../data/supportResources'
import {
  fetchSafetyPlan,
  saveSafetyPlan,
  fetchTrustedContacts,
  createTrustedContact,
  deleteTrustedContact,
  type TrustedContactOut,
} from '../api/client'

// 编辑态里字段恒为 string（用 '' 代表空），提交时才转换成 API 需要的 string | null
interface SafetyPlanDraft {
  warning_signs: string
  internal_coping: string
  distraction_people_places: string
  help_contacts: string
  professional_contacts: string
  safe_environment: string
}

const EMPTY_PLAN: SafetyPlanDraft = {
  warning_signs: '',
  internal_coping: '',
  distraction_people_places: '',
  help_contacts: '',
  professional_contacts: '',
  safe_environment: '',
}

const PLAN_FIELDS: { key: keyof SafetyPlanDraft; label: string; placeholder: string }[] = [
  { key: 'warning_signs', label: '预警信号', placeholder: '什么样的想法/感受/行为，说明状态在变差？' },
  { key: 'internal_coping', label: '内在应对策略', placeholder: '不需要联系任何人，我自己可以做什么？' },
  { key: 'distraction_people_places', label: '让自己分心的人/地方', placeholder: '可以带来正常感的人或地方' },
  { key: 'help_contacts', label: '可以求助的人', placeholder: '遇到困难时，我可以联系……' },
  { key: 'professional_contacts', label: '专业求助渠道', placeholder: '医生/咨询师/热线等' },
  { key: 'safe_environment', label: '让环境更安全', placeholder: '怎么减少接触到可能伤害自己的东西' },
]

export default function Support() {
  const [plan, setPlan] = useState<SafetyPlanDraft>(EMPTY_PLAN)
  const [planSaving, setPlanSaving] = useState(false)
  const [planSaved, setPlanSaved] = useState(false)

  const [contacts, setContacts] = useState<TrustedContactOut[]>([])
  const [newContact, setNewContact] = useState({ name: '', relationship: '', phone: '' })

  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    fetchSafetyPlan()
      .then((p) => {
        if (p) {
          setPlan({
            warning_signs: p.warning_signs ?? '',
            internal_coping: p.internal_coping ?? '',
            distraction_people_places: p.distraction_people_places ?? '',
            help_contacts: p.help_contacts ?? '',
            professional_contacts: p.professional_contacts ?? '',
            safe_environment: p.safe_environment ?? '',
          })
        }
      })
      .catch((e) => setError(e.message))

    fetchTrustedContacts()
      .then(setContacts)
      .catch((e) => setError(e.message))
  }, [])

  async function handleSavePlan() {
    setPlanSaving(true)
    setPlanSaved(false)
    try {
      await saveSafetyPlan(plan)
      setPlanSaved(true)
      setTimeout(() => setPlanSaved(false), 2000)
    } catch (e: any) {
      setError(e.message)
    } finally {
      setPlanSaving(false)
    }
  }

  async function addContact() {
    if (!newContact.name.trim()) return
    try {
      const created = await createTrustedContact({
        name: newContact.name,
        relationship: newContact.relationship || undefined,
        phone: newContact.phone || undefined,
      })
      setContacts((prev) => [...prev, created])
      setNewContact({ name: '', relationship: '', phone: '' })
    } catch (e: any) {
      setError(e.message)
    }
  }

  async function removeContact(id: string) {
    const prevContacts = contacts
    setContacts((prev) => prev.filter((c) => c.id !== id))
    try {
      await deleteTrustedContact(id)
    } catch (e: any) {
      setError(e.message)
      setContacts(prevContacts) // 回滚
    }
  }

  return (
    <div className="flex flex-col h-full">
      <div className="px-6 md:px-10 py-5 shrink-0 border-b border-paper-sunk">
        <h1 className="font-display text-2xl font-bold text-ink mb-0.5">支持</h1>
        <p className="text-ink-soft/80 text-sm">需要的时候，这里都在</p>
      </div>

      <div className="flex-1 overflow-y-auto bg-paper">
        <div className="max-w-2xl mx-auto px-4 md:px-6 py-6 space-y-4">
        {error && <p className="text-red-500 text-sm">{error}</p>}

        {/* 安全计划 */}
        <div className="bg-paper-surface rounded-2xl px-5 py-4 border border-paper-sunk/60">
          <p className="text-sm font-medium text-ink mb-3">安全计划</p>
          <div className="space-y-3">
            {PLAN_FIELDS.map(({ key, label, placeholder }) => (
              <div key={key}>
                <label className="text-xs text-ink-soft mb-1 block">{label}</label>
                <textarea
                  value={plan[key]}
                  onChange={(e) => setPlan((p) => ({ ...p, [key]: e.target.value }))}
                  placeholder={placeholder}
                  rows={2}
                  className="w-full bg-paper-sunk rounded-xl px-3 py-2 text-sm text-ink placeholder-ink-soft/70 focus:outline-none focus:ring-2 focus:ring-accent-300 resize-none"
                />
              </div>
            ))}
          </div>
          <button
            onClick={handleSavePlan}
            disabled={planSaving}
            className="w-full mt-3 py-2 rounded-xl bg-accent-500 text-white text-sm font-medium hover:bg-accent-600 active:scale-[0.98] transition disabled:opacity-50"
          >
            {planSaving ? '保存中…' : planSaved ? '已保存 ✓' : '保存安全计划'}
          </button>
        </div>

        {/* 应对工具 */}
        <div className="bg-paper-surface rounded-2xl px-5 py-4 border border-paper-sunk/60">
          <p className="text-sm font-medium text-ink mb-3">应对工具</p>
          <div className="space-y-3">
            {COPING_TOOLS.map(({ icon: Icon, title, description }) => (
              <div key={title} className="flex gap-3">
                <div className="w-8 h-8 rounded-full bg-accent-50 flex items-center justify-center shrink-0">
                  <Icon className="w-4 h-4 text-accent-500" strokeWidth={2} />
                </div>
                <div>
                  <p className="text-sm text-ink font-medium">{title}</p>
                  <p className="text-xs text-ink-soft leading-relaxed mt-0.5">{description}</p>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* 可信联系人 */}
        <div className="bg-paper-surface rounded-2xl px-5 py-4 border border-paper-sunk/60">
          <p className="text-sm font-medium text-ink mb-3">可信联系人</p>

          {contacts.length > 0 && (
            <div className="space-y-2 mb-3">
              {contacts.map((c) => (
                <div key={c.id} className="flex items-center gap-3 bg-paper-sunk rounded-xl px-3 py-2.5">
                  <div className="flex-1 min-w-0">
                    <p className="text-sm text-ink">{c.name}{c.relationship && <span className="text-ink-soft"> · {c.relationship}</span>}</p>
                    {c.phone && <p className="font-mono text-xs tabular-nums text-ink-soft">{c.phone}</p>}
                  </div>
                  <button
                    onClick={() => removeContact(c.id)}
                    aria-label={`删除联系人：${c.name}`}
                    className="text-ink-soft hover:text-red-500 shrink-0 transition-transform active:scale-90"
                  >
                    <Trash2 className="w-4 h-4" />
                  </button>
                </div>
              ))}
            </div>
          )}

          <div className="grid grid-cols-2 gap-2 mb-2">
            <input
              value={newContact.name}
              onChange={(e) => setNewContact((c) => ({ ...c, name: e.target.value }))}
              placeholder="姓名"
              className="bg-paper-sunk rounded-xl px-3 py-2 text-sm text-ink placeholder-ink-soft/70 focus:outline-none focus:ring-2 focus:ring-accent-300 col-span-1"
            />
            <input
              value={newContact.relationship}
              onChange={(e) => setNewContact((c) => ({ ...c, relationship: e.target.value }))}
              placeholder="关系"
              className="bg-paper-sunk rounded-xl px-3 py-2 text-sm text-ink placeholder-ink-soft/70 focus:outline-none focus:ring-2 focus:ring-accent-300 col-span-1"
            />
            <input
              value={newContact.phone}
              onChange={(e) => setNewContact((c) => ({ ...c, phone: e.target.value }))}
              placeholder="电话"
              className="bg-paper-sunk rounded-xl px-3 py-2 text-sm text-ink placeholder-ink-soft/70 focus:outline-none focus:ring-2 focus:ring-accent-300 col-span-2"
            />
          </div>
          <button
            onClick={addContact}
            className="w-full flex items-center justify-center gap-1.5 py-2 rounded-xl bg-accent-50 text-accent-600 text-sm font-medium hover:bg-accent-100 active:scale-[0.98] transition"
          >
            <Plus className="w-4 h-4" /> 添加联系人
          </button>
        </div>

        {/* 专业机构 */}
        <div className="bg-paper-surface rounded-2xl px-5 py-4 border border-paper-sunk/60">
          <p className="text-sm font-medium text-ink mb-3">专业机构</p>
          <div className="space-y-3">
            {PROFESSIONAL_ORGS.map((org) => (
              <a
                key={org.name}
                href={`tel:${org.phone}`}
                className="flex items-center gap-3 bg-paper-sunk rounded-xl px-3 py-2.5 hover:bg-sage-300/30 transition-colors"
              >
                <div className="w-8 h-8 rounded-full bg-sage-300/40 flex items-center justify-center shrink-0">
                  <Phone className="w-4 h-4 text-sage-600" strokeWidth={2} />
                </div>
                <div className="flex-1 min-w-0">
                  <p className="text-sm text-ink">{org.name}</p>
                  <p className="text-xs text-ink-soft">{org.description}</p>
                </div>
                <div className="text-right shrink-0">
                  <p className="font-mono text-sm tabular-nums text-ink">{org.phone}</p>
                  <p className="text-[10px] text-ink-soft">{org.hours}</p>
                </div>
              </a>
            ))}
          </div>
        </div>
        </div>
      </div>
    </div>
  )
}
