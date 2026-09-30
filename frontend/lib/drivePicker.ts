/* Google 의 파일 선택 창(Picker, plan/75).

   권한이 drive.file 이라 이 앱은 사용자가 여기서 고른 파일만 연다. 창은 Google 이 그리고, 고른 파일의 id 만
   돌려받는다. 필요한 스크립트는 처음 열 때 한 번 받는다. setAppId(프로젝트 번호)가 있어야 고른 파일이
   이 앱에 허락된다. */

declare global { interface Window { gapi?: any; google?: any } }

let loading: Promise<void> | null = null;

function load(): Promise<void> {
  if (window.google?.picker) return Promise.resolve();
  if (!loading) {
    loading = new Promise<void>((resolve, reject) => {
      const fail = () => { loading = null; reject(new Error("drive_picker_load")); };
      const s = document.createElement("script");
      s.src = "https://apis.google.com/js/api.js";
      s.async = true;
      s.onload = () => window.gapi.load("picker", { callback: () => resolve(), onerror: fail, timeout: 15000, ontimeout: fail });
      s.onerror = fail;
      document.head.appendChild(s);
    });
  }
  return loading;
}

export interface PickedFile { id: string; name: string }

/** 창을 열고 고른 파일을 돌려준다. 닫으면 null. */
export async function pickDriveFiles(o: { token: string; apiKey: string; appId: string; locale: string; title: string; max: number }): Promise<PickedFile[] | null> {
  await load();
  const g = window.google.picker;
  return new Promise((resolve) => {
    const docs = new g.DocsView(g.ViewId.DOCS).setIncludeFolders(true).setSelectFolderEnabled(false);
    const b = new g.PickerBuilder()
      .addView(docs)
      .enableFeature(g.Feature.MULTISELECT_ENABLED)
      .setMaxItems(o.max)
      .setOAuthToken(o.token)
      .setDeveloperKey(o.apiKey)
      .setLocale(o.locale)
      .setTitle(o.title)
      .setOrigin(window.location.origin)
      .setCallback((data: any) => {
        const action = data[g.Response.ACTION];
        if (action === g.Action.PICKED) {
          resolve((data[g.Response.DOCUMENTS] ?? []).map((d: any) => ({ id: String(d[g.Document.ID]), name: String(d[g.Document.NAME] ?? "") })));
        } else if (action === g.Action.CANCEL) resolve(null);
      });
    if (o.appId) b.setAppId(o.appId);
    b.build().setVisible(true);
  });
}
