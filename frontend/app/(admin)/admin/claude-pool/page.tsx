import { redirect } from "next/navigation";

/** Claude accounts moved in with the provider they belong to. Kept as a redirect so a
 *  bookmark from the day this had its own menu entry still lands on them. */
export default function Page() { redirect("/admin/providers"); }
