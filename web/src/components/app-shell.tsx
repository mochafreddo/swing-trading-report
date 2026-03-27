import { MainNav } from "@/components/main-nav";

type AppShellProps = {
  children: React.ReactNode;
};

export function AppShell({ children }: AppShellProps) {
  return (
    <div className="app-shell">
      <header className="top-bar">
        <div className="top-bar-copy">
          <p className="eyebrow">Swing Trading Report</p>
          <h1 className="title">Operations Console</h1>
          <p className="lede">
            리포트 검토, 보유 조정, 워크플로 실행을 같은 작업면에서 처리합니다.
          </p>
        </div>
        <div className="top-bar-side">
          <div className="header-note">
            <p className="header-note-label">Control Surface</p>
            <p className="header-note-copy">
              리포트, 보유, 실행 제어를 하나의 운영 흐름으로 정리했습니다.
            </p>
          </div>
          <MainNav />
        </div>
      </header>
      <main className="main-content">{children}</main>
    </div>
  );
}
