import { mkdir, lstat, symlink, readFile, realpath } from 'node:fs/promises';
import { resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const data = process.argv[2];
if (!data) throw new Error('Usage: node scripts/link-data.mjs /absolute/path/to/data/web');
await readFile(resolve(data, 'catalog/manifest.json'));
await readFile(resolve(data, 'assets/manifest.json'));
await mkdir(resolve(root, 'public'), { recursive: true });
for (const name of ['assets', 'catalog']) {
  const target = resolve(data, name);
  const link = resolve(root, 'public', name);
  const stat = await lstat(link).catch(e => { if (e.code === 'ENOENT') return null; throw e; });
  if (stat) {
    if (!stat.isSymbolicLink() || await realpath(link) !== await realpath(target)) throw new Error(`Refusing to replace existing ${link}`);
  } else await symlink(target, link, 'dir');
}
console.log('Local catalog and images connected.');
