// Official Khronos validator adapter. Resources stay within the asset directory.
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
async function main() {
  const [modulePath, filename, limit, resourceRoot] = process.argv.slice(2);
  const validator = require(modulePath);
  const source = fs.realpathSync(filename);
  const root = fs.realpathSync(resourceRoot || path.dirname(source));
  const bytes = fs.readFileSync(source);
  const resources = [];
  const report = await validator.validateBytes(new Uint8Array(bytes.buffer, bytes.byteOffset, bytes.byteLength), {
    uri: path.basename(source), maxIssues: Number(limit),
    externalResourceFunction: async uri => {
      const decoded = decodeURIComponent(uri);
      if (/^[a-z][a-z0-9+.-]*:/i.test(decoded) || path.isAbsolute(decoded)) throw new Error('Only relative local asset resources are allowed');
      const candidate = fs.realpathSync(path.resolve(path.dirname(source), decoded));
      const relative = path.relative(root, candidate);
      if (relative.startsWith('..' + path.sep) || relative === '..' || path.isAbsolute(relative)) throw new Error('Asset resource leaves its directory');
      const data = fs.readFileSync(candidate);
      resources.push({uri, bytes:data.length, sha256:crypto.createHash('sha256').update(data).digest('hex')});
      return new Uint8Array(data.buffer, data.byteOffset, data.byteLength);
    }
  });
  process.stdout.write(JSON.stringify({report, resources, source_sha256:crypto.createHash('sha256').update(bytes).digest('hex')}));
}
main().catch(error => { process.stderr.write(String(error)); process.exitCode = 1; });
