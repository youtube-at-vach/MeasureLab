import { spawn } from 'node:child_process';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const scriptDirectory = path.dirname(fileURLToPath(import.meta.url));
export const projectRoot = path.resolve(scriptDirectory, '../..');

const executable = (name) =>
  path.join(projectRoot, 'node_modules', '.bin', `${name}${process.platform === 'win32' ? '.cmd' : ''}`);

export function runCommand(command, args, { capture = false } = {}) {
  return new Promise((resolve, reject) => {
    const child = spawn(command, args, {
      cwd: projectRoot,
      env: process.env,
      stdio: capture ? ['ignore', 'pipe', 'pipe'] : 'inherit',
    });
    let stdout = '';
    let stderr = '';

    if (capture) {
      child.stdout.setEncoding('utf8');
      child.stderr.setEncoding('utf8');
      child.stdout.on('data', (chunk) => {
        stdout += chunk;
      });
      child.stderr.on('data', (chunk) => {
        stderr += chunk;
      });
    }

    child.once('error', reject);
    child.once('exit', (code, signal) => {
      if (code === 0) {
        resolve({ stdout, stderr });
        return;
      }
      reject(
        new Error(
          `${path.basename(command)} exited with ${code ?? `signal ${signal}`}\n${stdout}${stderr}`,
        ),
      );
    });
  });
}

async function waitUntilReady(url, timeoutMilliseconds = 30_000) {
  const deadline = Date.now() + timeoutMilliseconds;
  let lastError;

  while (Date.now() < deadline) {
    try {
      const response = await fetch(url);
      if (response.ok) return;
      lastError = new Error(`Preview returned HTTP ${response.status}.`);
    } catch (error) {
      lastError = error;
    }

    await new Promise((resolve) => setTimeout(resolve, 100));
  }

  throw new Error(`Preview did not become ready at ${url}: ${lastError}`);
}

export async function withPreview(callback, { port }) {
  const origin = `http://127.0.0.1:${port}`;
  const documentationRoot = `${origin}/MeasureLab/`;
  let started = false;

  try {
    await runCommand(executable('astro'), [
      'preview',
      '--background',
      '--host',
      '127.0.0.1',
      '--port',
      String(port),
    ]);
    started = true;
    await waitUntilReady(documentationRoot);
    return await callback({ origin, documentationRoot });
  } finally {
    if (started) {
      await runCommand(executable('astro'), ['preview', 'stop']);
    }
  }
}

export const localExecutable = executable;
