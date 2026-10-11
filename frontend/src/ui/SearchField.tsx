import { useEffect, useEffectEvent, useState } from "react";

/**
 * A search box that keeps what is being typed to itself and hands the value on only after a
 * pause (or Enter). The page above it re-renders once per search, not once per keystroke.
 * When `value` changes from outside (back/forward, a cleared filter) the box follows it.
 */
export function SearchField({
  id,
  label,
  value,
  onCommit,
  placeholder,
  minLength = 2,
  maxLength = 120,
  delay = 350,
  hideLabel = false,
}: {
  id: string;
  label: string;
  value: string;
  onCommit: (value: string) => void;
  placeholder?: string;
  minLength?: number;
  maxLength?: number;
  delay?: number;
  hideLabel?: boolean;
}) {
  const [text, setText] = useState(value);
  const [synced, setSynced] = useState(value);
  if (value !== synced) {
    setSynced(value);
    setText(value);
  }

  const commit = (raw: string) => {
    const v = raw.trim();
    if (v !== value && (v.length >= minLength || v.length === 0)) onCommit(v);
  };
  // the timer reads the latest props without restarting when the parent re-renders
  const commitLater = useEffectEvent(commit);

  useEffect(() => {
    const timer = setTimeout(() => commitLater(text), delay);
    return () => clearTimeout(timer);
  }, [text, delay]);

  return (
    <div className="field field--grow">
      <label htmlFor={id} className={hideLabel ? "visually-hidden" : undefined}>
        {label}
      </label>
      <input
        id={id}
        type="search"
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter") {
            e.preventDefault();
            commit(text);
          }
        }}
        placeholder={placeholder}
        maxLength={maxLength}
      />
    </div>
  );
}
