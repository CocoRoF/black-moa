import type { HTMLAttributes, ReactNode } from "react";
import { cn } from "@/lib/utils";

export function Card({ className, ...p }: HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("rounded-2xl border border-border bg-card shadow-soft", className)} {...p} />;
}
export function CardHeader({ title, description, action, className }: { title: ReactNode; description?: ReactNode; action?: ReactNode; className?: string }) {
  return (
    <div className={cn("flex items-start justify-between gap-3 px-5 pt-5 pb-3", className)}>
      <div className="min-w-0">
        <h3 className="text-[15px] font-semibold leading-tight">{title}</h3>
        {description ? <p className="mt-1 text-sm text-muted-fg">{description}</p> : null}
      </div>
      {action ? <div className="shrink-0">{action}</div> : null}
    </div>
  );
}
export function CardBody({ className, ...p }: HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("px-5 pb-5", className)} {...p} />;
}
export function Section({ title, description, children, action, className }: { title: ReactNode; description?: ReactNode; children: ReactNode; action?: ReactNode; className?: string }) {
  return (
    <Card className={className}>
      <CardHeader title={title} description={description} action={action} />
      <CardBody>{children}</CardBody>
    </Card>
  );
}
