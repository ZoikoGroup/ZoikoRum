import { useEffect, useState } from 'react'
import { blockNonIntegerKey, integerError, keepDigits } from '../lib/validation'

/** A whole-number box: blocks e E . , + - and strips anything that is not a digit (typed or pasted). `onCommit` gets the number,
 *  or null when empty. Out-of-range values are clamped on blur with a message; the message clears on the next keystroke. */
export default function IntInput({ value, min, max, onCommit, className = 'input', ...rest }: {
  value: number | null; min: number; max?: number; onCommit: (n: number | null) => void; className?: string
} & Omit<React.InputHTMLAttributes<HTMLInputElement>, 'value' | 'onChange' | 'type' | 'min' | 'max'>) {
  const [text, setText] = useState(value == null ? '' : String(value))
  const [error, setError] = useState('')
  useEffect(() => { setText((cur) => (value == null ? (cur === '' ? cur : '') : cur !== '' && Number(cur) === value ? cur : String(value))) }, [value])
  const inRange = (n: number) => n >= min && (max === undefined || n <= max)
  return <>
    <input {...rest} className={className} type="text" inputMode="numeric" pattern="[0-9]*" autoComplete="off" value={text}
      aria-invalid={error ? true : undefined}
      onKeyDown={blockNonIntegerKey}
      onChange={(e) => {
        const v = keepDigits(e.target.value); setText(v); setError('')
        if (v === '') onCommit(null); else if (inRange(Number(v))) onCommit(Number(v))
      }}
      onBlur={() => {
        if (text === '') return
        const msg = integerError(text, min, max)
        if (!msg) return
        const n = Math.min(max ?? Infinity, Math.max(min, Number(text)))
        setText(String(n)); setError(msg); onCommit(n)
      }} />
    {error && <span className="small warn-text" role="alert" style={{ display: 'block' }}>{error}</span>}
  </>
}
