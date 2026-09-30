export function StreamingCursor() {
  return <span aria-hidden className="cursor-blink ml-0.5 inline-block h-[1em] w-[2px] translate-y-[0.15em] bg-current align-baseline" />;
}
export function TypingDots({ className }: { className?: string }) {
  return (
    <span className={className} aria-hidden>
      <span className="typing-dot inline-block h-1.5 w-1.5 rounded-full bg-current mx-[1.5px]" />
      <span className="typing-dot inline-block h-1.5 w-1.5 rounded-full bg-current mx-[1.5px]" />
      <span className="typing-dot inline-block h-1.5 w-1.5 rounded-full bg-current mx-[1.5px]" />
    </span>
  );
}
