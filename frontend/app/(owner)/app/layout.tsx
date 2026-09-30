import { OwnerShell } from "@/components/owner/Shell";
export default function OwnerLayout({ children }: { children: React.ReactNode }) {
  return <OwnerShell>{children}</OwnerShell>;
}
