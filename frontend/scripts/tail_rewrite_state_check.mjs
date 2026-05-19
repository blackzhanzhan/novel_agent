import { findLatestUserMessage, rewriteTailMessages } from '../src/lib/tailRewrite.js'

function assert(condition, message) {
  if (!condition)
    throw new Error(message)
}

const sampleMessages = [
  { id: 'u1', role: 'user', text: '第一问', status: 'done' },
  { id: 'a1', role: 'assistant', text: '第一答', status: 'done' },
  { id: 'u2', role: 'user', text: '错别字问题', status: 'done' },
  { id: 'a2', role: 'assistant', text: '中断回答', status: 'interrupted' },
]

const latestUser = findLatestUserMessage(sampleMessages)
assert(latestUser?.id === 'u2', '应命中最后一条用户消息 u2')

const rewritten = rewriteTailMessages(sampleMessages, 'u2', '修正后的最后一问')
assert(rewritten.length === 3, '尾部重写后只应保留到最后一条用户消息')
assert(rewritten[0].id === 'u1', '前文用户消息应保留')
assert(rewritten[1].id === 'a1', '前文 assistant 消息应保留')
assert(rewritten[2].id === 'u2', '最后一条用户消息应仍在原位置')
assert(rewritten[2].text === '修正后的最后一问', '最后一条用户消息文本应被替换')
assert(!rewritten.some(message => message.id === 'a2'), '被中断的尾部 assistant 消息应被尾部重写移除')

console.log('tail_rewrite_state_check: ok')
