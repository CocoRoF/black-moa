"use client";
import { Children, forwardRef, type ButtonHTMLAttributes } from "react";
import { Loader2 } from "@/components/icons";
import { cn } from "@/lib/utils";

export type ButtonVariant = "primary" | "accent" | "secondary" | "ghost" | "outline" | "danger" | "link";
export type ButtonSize = "sm" | "md" | "lg" | "icon" | "icon-sm";

const variants: Record<ButtonVariant, string> = {
  primary: "bg-primary text-primary-fg hover:opacity-90 shadow-sm",
  accent: "bg-accent text-accent-fg hover:opacity-90 shadow-sm",
  secondary: "bg-muted text-fg hover:bg-border/70",
  ghost: "bg-transparent hover:bg-muted text-fg",
  outline: "border border-border bg-card hover:bg-muted text-fg",
  danger: "bg-danger text-danger-fg hover:opacity-90",
  link: "bg-transparent text-accent underline-offset-4 hover:underline px-0 h-auto",
};
const BASE = "inline-flex items-center justify-center font-medium whitespace-nowrap select-none transition-[background,opacity,transform] active:scale-[0.98] disabled:opacity-50 disabled:pointer-events-none focus-visible:outline-2 focus-visible:outline-ring focus-visible:outline-offset-2";
/** 높이는 40px 이 최대다(2026-09-30): sm 32 · md 36 · lg 40. 입력칸·셀렉터·날짜는 40, 탭형 토글은 36 —
 *  한 줄에 섞여도 어긋나지 않는 세 칸. 44px 는 휴대폰 손가락을 핑계로 모든 화면을 무겁게 했다. */
const sizes: Record<ButtonSize, string> = {
  sm: "h-8 px-3 text-[13px] rounded-lg gap-1.5",
  md: "h-9 px-3.5 text-sm rounded-xl gap-1.5",
  lg: "h-10 px-4 text-[15px] rounded-xl gap-2",
  icon: "h-9 w-9 rounded-xl",
  "icon-sm": "h-8 w-8 rounded-lg",
};

/** The look of a button, for something that is not one.
 *
 *  A link that looks like a button is a link: `<Link><Button/></Link>` puts a button inside
 *  an anchor, which is markup no parser keeps and two nested things to press. Give the
 *  <Link> this instead. */
export function buttonLook(variant: ButtonVariant = "primary", size: ButtonSize = "md", className?: string) {
  return cn(BASE, variants[variant], sizes[size], className);
}

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant; size?: ButtonSize; loading?: boolean;
}
export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button({ className, variant = "primary", size = "md", loading, disabled, children, type = "button", ...rest }, ref) {
  // 도는 동그라미는 아이콘의 **자리를 대신한다**. 둘을 같이 두면 아이콘만 있는
  // 버튼에서는 한 원 안에 두 개가 겹치고, 글자가 있는 버튼에서는 동그라미·아이콘·글자가
  // 줄줄이 선다. 도는 동안에는 글자만 남긴다.
  const shown = loading ? Children.toArray(children).filter((c) => typeof c === "string" || typeof c === "number") : children;
  return (
    <button ref={ref} type={type} disabled={disabled || loading} aria-busy={loading || undefined}
      className={cn(BASE, variants[variant], sizes[size], className)} {...rest}>
      {loading ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : null}
      {shown}
    </button>
  );
});
