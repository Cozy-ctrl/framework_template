import { ExecError, SpritesClient } from '@fly/sprites';

const RESULT_MARKER = '__SPRITE_RESULT__';

function parseArgs(argv) {
  const args = {};
  for (let i = 0; i < argv.length; i += 1) {
    const token = argv[i];
    if (!token.startsWith('--')) {
      continue;
    }
    const key = token.slice(2);
    const value = argv[i + 1];
    if (!value || value.startsWith('--')) {
      args[key] = 'true';
      continue;
    }
    args[key] = value;
    i += 1;
  }
  return args;
}

async function run() {
  const args = parseArgs(process.argv.slice(2));

  const topic = args.topic;
  const model = args.model || 'gateway/openai:gpt-5.2';
  const provider = args.provider || 'openai';
  const outputDir = args['output-dir'] || '/workspace/framework_template/output';
  const gitRepo = args['git-repo'];
  const gitRef = args['git-ref'] || '';
  const withAudio = args['with-audio'] === 'true';
  const keepSprite = args['keep-sprite'] === 'true';

  const spritesToken = process.env.SPRITES_TOKEN || process.env.SPRITE_TOKEN;
  const gatewayApiKey = process.env.PYDANTIC_AI_GATEWAY_API_KEY;
  const cartesiaApiKey = process.env.CARTESIA_API_KEY || '';
  const bunnyStorageRegion = process.env.BUNNY_STORAGE_REGION || '';
  const bunnyStorageZone = process.env.BUNNY_STORAGE_ZONE || '';
  const bunnyStorageAccessKey = process.env.BUNNY_STORAGE_ACCESS_KEY || '';
  const bunnyStoragePrefix = process.env.BUNNY_STORAGE_PREFIX || '';

  if (!spritesToken) {
    throw new Error('Missing SPRITES_TOKEN (or SPRITE_TOKEN).');
  }
  if (!topic) {
    throw new Error('Missing --topic argument.');
  }
  if (!gitRepo) {
    throw new Error('Missing --git-repo argument.');
  }
  if (!gatewayApiKey) {
    throw new Error('Missing PYDANTIC_AI_GATEWAY_API_KEY.');
  }
  if (withAudio && !cartesiaApiKey) {
    throw new Error('Audio enabled but CARTESIA_API_KEY is missing.');
  }
  if (withAudio && (!bunnyStorageRegion || !bunnyStorageZone || !bunnyStorageAccessKey)) {
    throw new Error(
      'Audio enabled but Bunny upload configuration is missing. Set BUNNY_STORAGE_REGION, BUNNY_STORAGE_ZONE, and BUNNY_STORAGE_ACCESS_KEY.'
    );
  }

  const client = new SpritesClient(spritesToken);
  const spriteName = args['sprite-name'] || `template-agent-${Date.now()}`;
  const sprite = await client.createSprite(spriteName);

  try {
    console.log(`[sprite] Created ${spriteName}`);
    console.log('[sprite] Bootstrapping project in sprite...');

    await sprite.execFile(
      'bash',
      [
        '-lc',
        [
          'set -euo pipefail',
          'mkdir -p /workspace',
          'rm -rf /workspace/framework_template',
          'git clone --depth 1 "$GIT_REPO" /workspace/framework_template',
          'if [ -n "$GIT_REF" ]; then',
          '  cd /workspace/framework_template',
          '  git fetch --depth 1 origin "$GIT_REF"',
          '  git checkout "$GIT_REF"',
          'fi',
          'cd /workspace/framework_template',
          'python3 -m venv .venv',
          '/workspace/framework_template/.venv/bin/python3 -m pip install -r requirements.txt',
        ].join('\n'),
      ],
      {
        env: {
          GIT_REPO: gitRepo,
          GIT_REF: gitRef,
        },
        maxBuffer: 100 * 1024 * 1024,
      }
    );

    console.log('[sprite] Running template_agent.cli inside sprite...');
    const cliArgs = [
      '-m',
      'template_agent.cli',
      topic,
      '--model',
      model,
      '--provider',
      provider,
      '--output-dir',
      outputDir,
    ];

    if (withAudio) {
      cliArgs.push('--with-audio');
    }

    const runResult = await sprite.execFile(
      '/workspace/framework_template/.venv/bin/python3',
      cliArgs,
      {
        cwd: '/workspace/framework_template',
        env: {
          PYDANTIC_AI_GATEWAY_API_KEY: gatewayApiKey,
          GATEWAY_MODEL: model,
          GATEWAY_PROVIDER: provider,
          ...(withAudio ? { CARTESIA_API_KEY: cartesiaApiKey } : {}),
          ...(bunnyStorageRegion ? { BUNNY_STORAGE_REGION: bunnyStorageRegion } : {}),
          ...(bunnyStorageZone ? { BUNNY_STORAGE_ZONE: bunnyStorageZone } : {}),
          ...(bunnyStorageAccessKey ? { BUNNY_STORAGE_ACCESS_KEY: bunnyStorageAccessKey } : {}),
          ...(bunnyStoragePrefix ? { BUNNY_STORAGE_PREFIX: bunnyStoragePrefix } : {}),
        },
        maxBuffer: 100 * 1024 * 1024,
      }
    );

    if (runResult.stdout) {
      process.stdout.write(runResult.stdout);
    }
    if (runResult.stderr) {
      process.stderr.write(runResult.stderr);
    }

    const doneLine = runResult.stdout
      .split('\n')
      .find((line) => line.toLowerCase().startsWith('done. output folder:'));

    let runDir = '';
    if (doneLine) {
      runDir = doneLine.split(':').slice(1).join(':').trim();
    }

    if (!runDir) {
      throw new Error('Could not find output folder in CLI output.');
    }

    let audioBunnyUrl = '';
    if (withAudio) {
      const bunnyUrlRaw = await sprite.execFile('cat', [`${runDir}/written_stories_audio_bunny_url.txt`], {
        maxBuffer: 5 * 1024 * 1024,
      });
      audioBunnyUrl = bunnyUrlRaw.stdout.trim();
      if (!audioBunnyUrl) {
        throw new Error('Audio run completed but Bunny upload URL was empty.');
      }
    }

    const planRaw = await sprite.execFile('cat', [`${runDir}/story_plan.json`], {
      maxBuffer: 20 * 1024 * 1024,
    });
    const writtenRaw = await sprite.execFile('cat', [`${runDir}/written_stories.json`], {
      maxBuffer: 20 * 1024 * 1024,
    });

    const payload = {
      runDir,
      spriteName,
      audioBunnyUrl,
      plan: JSON.parse(planRaw.stdout),
      written: JSON.parse(writtenRaw.stdout),
    };

    console.log(`${RESULT_MARKER}${JSON.stringify(payload)}`);
  } finally {
    if (keepSprite) {
      console.log(`[sprite] Keeping sprite ${spriteName} (per --keep-sprite).`);
    } else {
      await sprite.delete();
      console.log(`[sprite] Deleted ${spriteName}`);
    }
  }
}

run().catch((error) => {
  if (error instanceof ExecError) {
    console.error(`Sprite command failed (exit ${error.exitCode})`);
    if (error.stdout) {
      process.stdout.write(error.stdout);
    }
    if (error.stderr) {
      process.stderr.write(error.stderr);
    }
  }

  const message = error instanceof Error ? error.message : String(error);
  console.error(message);
  process.exit(1);
});
