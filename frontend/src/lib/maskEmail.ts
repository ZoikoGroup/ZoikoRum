/** "alice@example.com" -> "a***@example.com": names the destination without showing the whole address. */
export function maskEmail(email: string | null | undefined): string {
  if (!email || !email.includes('@')) return 'your registered email'
  const [name, domain] = [email.slice(0, email.lastIndexOf('@')), email.slice(email.lastIndexOf('@') + 1)]
  return `${name.slice(0, 1)}***@${domain}`
}
