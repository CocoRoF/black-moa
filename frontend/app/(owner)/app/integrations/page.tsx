import { redirect } from "next/navigation";

/** [연동]은 [인증 및 연결]의 "연결"과 같은 것이라 하나로 합쳤다 (plan/81). 옛 주소와 연결 뒤 돌아오던 주소는 그리로. */
export default async function Page({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(await searchParams)) for (const x of [v ?? []].flat()) q.append(k, x);
  redirect(`/app/account${q.size ? `?${q}` : ""}#connections`);
}
