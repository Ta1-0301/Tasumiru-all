// src/icons.ts
//
// Lucideアイコンのブートストラップ。auth/router.ts・pipeline/router.tsと同じ方針で、
// 既存の app.ts には一切手を入れず、この独立したモジュールが同じ DOMContentLoaded に
// 相乗りする。
//
// このアプリはビュー描画箇所(innerHTML代入)が pipeline/router.ts の集約ディスパッチ
// 1箇所以外にも auth/router.ts の複数箇所、app.ts のレガシー箇所、
// taskGenerationProgress.ts のポーリング毎の再描画など散在しているため、
// 個別に createIcons() を挿し込むのではなく、DOM変化を監視して自動的に
// <i data-lucide="..."> を <svg> に変換する。
//
// createIcons() は data-lucide 要素を <svg> に置換し、生成された <svg> は
// data-lucide 属性を持たないため、再スキャンしても無限ループにはならない。
import { createIcons, icons } from "lucide";

function activateIcons(): void {
  createIcons({ icons });
}

document.addEventListener("DOMContentLoaded", () => {
  activateIcons();

  // style.display / class の頻繁なトグル（画面切り替え等）で不要に発火しないよう、
  // attributes は監視しない。childList/subtreeだけで新規追加要素を検知する。
  let scheduled = false;
  const observer = new MutationObserver(() => {
    if (scheduled) return;
    scheduled = true;
    requestAnimationFrame(() => {
      scheduled = false;
      activateIcons();
    });
  });
  observer.observe(document.body, { childList: true, subtree: true });
});
