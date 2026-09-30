import { MarketingShell } from "@/components/marketing/Shell";

export default function MarketingLayout({ children }: { children: React.ReactNode }) {
  return <MarketingShell>{children}</MarketingShell>;
}
