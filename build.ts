import tailwind from 'bun-plugin-tailwind'

const config = {
  entrypoints: ['./src/index.ts'],
  plugins: [tailwind],
  minify: true,
  target: 'bun',
  metafile: false,
  define: {
    'process.env.NODE_ENV': JSON.stringify('production'),
  },
} satisfies Bun.BuildConfig

await Bun.build({
  ...config,
  outdir: './dist',
})

await Bun.build({
  ...config,
  compile: {
    outfile: 'server',
  },
  outdir: './out',
  bytecode: true,
})
