export function findLatestUserMessage(messages) {
  if (!Array.isArray(messages)) return null
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    const message = messages[index]
    if (message && message.role === 'user')
      return message
  }
  return null
}

export function rewriteTailMessages(messages, targetUserMessageId, nextText) {
  if (!Array.isArray(messages))
    return []
  const targetIndex = messages.findIndex(message => message && message.id === targetUserMessageId && message.role === 'user')
  if (targetIndex < 0)
    return messages

  return messages.slice(0, targetIndex + 1).map((message, index) => {
    if (index !== targetIndex)
      return message
    return {
      ...message,
      text: nextText,
    }
  })
}
