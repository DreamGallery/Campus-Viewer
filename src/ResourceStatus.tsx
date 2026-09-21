import { useEffect, useState } from 'react';
interface Status { state: string; phase?: string; last_success?: number }
export default function ResourceStatus({ error }: { error?: string }) {
  const [status, setStatus] = useState<Status | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    const load = () => fetch('/api/resources/status', { signal: controller.signal }).then(r => r.ok ? r.json() : null).then(setStatus).catch(() => {});
    load(); const timer = setInterval(load, 5000);
    return () => { controller.abort(); clearInterval(timer); };
  }, []);
  const managed = status && status.state !== 'unmanaged';
  return <main className="empty-state" role="status"><h1>{managed ? status.state === 'error' ? '资源初始化暂未完成' : '资源初始化中' : '正在加载剧情目录'}</h1><p>{managed ? status.phase : error || '请稍候…'}</p>{managed && <p>{status.state === 'error' ? '更新器会自动重试，可查看 updater 日志了解原因。' : '完成后将自动显示剧情目录。'}</p>}</main>;
}
