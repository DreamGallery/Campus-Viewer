import { useEffect, useState } from 'react';
interface Status { state: string; phase?: string; last_success?: number }
export default function ResourceStatus({ error }: { error?: string }) {
  const [status, setStatus] = useState<Status | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>, pending = false;
    async function load() {
      if (document.hidden || pending || controller.signal.aborted) return;
      pending = true;
      let delay = 15000;
      try {
        const response = await fetch('/api/resources/status', { signal: controller.signal });
        if (response.status === 429) delay = 60000;
        if (response.ok) {
          const value: Status = await response.json();
          if (!controller.signal.aborted) setStatus(value);
        }
      } catch { /* Retry while the page remains open. */ }
      finally {
        pending = false;
        if (!controller.signal.aborted) timer = setTimeout(load, delay);
      }
    }
    const visibilityChanged = () => { clearTimeout(timer); if (!document.hidden) void load(); };
    void load();
    document.addEventListener('visibilitychange', visibilityChanged);
    return () => { controller.abort(); clearTimeout(timer); document.removeEventListener('visibilitychange', visibilityChanged); };
  }, []);
  const managed = status && status.state !== 'unmanaged';
  return <main className="empty-state" role="status"><h1>{managed ? status.state === 'error' ? '资源初始化暂未完成' : '资源初始化中' : '正在加载剧情目录'}</h1><p>{managed ? status.phase : error || '请稍候…'}</p>{managed && <p>{status.state === 'error' ? '更新器会自动重试，可查看 updater 日志了解原因。' : '完成后将自动显示剧情目录。'}</p>}</main>;
}
