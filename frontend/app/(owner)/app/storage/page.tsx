import { redirect } from "next/navigation";
// 저장 공간은 [내 정보 → 파일] 의 위쪽이 되었다.
export default function Page() { redirect("/app/files"); }
