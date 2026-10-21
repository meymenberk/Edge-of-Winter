# Runtime Asset Structure

All artwork loaded by the game lives below `assets/`. Runtime paths come from the
side-effect-free `modules.paths` resolver; code must not search the process working
directory or select files by partial filename.

```text
assets/
├── audio/music/                 # Main-menu soundtrack (main_menu.wav)
├── backgrounds/main_menu/       # Main-menu landscape
├── bosses/platanus/             # PLATANUS animation and arena atlases
├── characters/player/           # Gameplay walk sheet and menu character preview
├── characters/villagers/        # Profession/direction villager atlas
├── terrain/overworld/           # Overworld terrain/object atlas
├── ui/character_customization/  # Hair, skin, shirt, and pants source panels
├── ui/menus/                    # Wooden main-menu buttons and title logo
└── vehicles/                    # Sailboat hull artwork
```

Enemies, animals, item icons, hearts, particles, maps, and interaction keycaps
are currently drawn procedurally. Villagers are extracted and cached from their
profession atlas. The runtime tree currently contains 12 image files: 2 boss atlases, 2 player
images, 2 customization panels, and one image each for the menu background,
menu buttons, title logo, overworld terrain, sailboat, and villagers. Diagnostic output and reference
captures are kept outside the runtime tree under `validation/`; the 62 captures
that previously sat at project root are preserved in
`validation/root_diagnostics/`.

## Adding artwork

Place a new file in the narrowest existing category (or add one useful category),
give it a unique descriptive filename, and reference the explicit path beneath
`modules.paths.ASSETS_DIR`. Do not add filename-search fallbacks or duplicate a file
at project root. If replacing artwork, verify its expected dimensions and update
tests/docs.

## Migration record

The project has no Git metadata, so this table records the pre-move source, final
destination, and SHA-256 identity used for the migration.

| Original | Destination | SHA-256 |
|---|---|---|
| `bg.jpeg` | `assets/backgrounds/main_menu/bg.jpeg` | `1c4d1fc5d8686831baa036aca1bc0e0bae5bdd54a2456dc7f4e75da38bc70c99` |
| `ChatGPT Görseli 16 Eki 2026 19_34_26.png` | `assets/characters/player/menu_character_preview.png` | `5b547f3c897787a830522a4fdba261eaba812882de87e665b8ae7475d8d8f50a` |
| `ChatGPT Görseli 16 Eki 2026 19_43_03.png` | `assets/ui/menus/main_menu_buttons.png` | `75c128f21aef8ce63f4454d1b15a011db649e2064b83d92cfe79f50aeb857fba` |
| `Fall Tile Set.png` | `assets/terrain/overworld/Fall Tile Set.png` | `5a6ba34edb85dec891dccc8e4cd788f3035ceef8685048d150602a457e896295` |
| `Retro Piksel Karakter Özelleştirme Arayüzü.png` | `assets/ui/character_customization/hair_and_skin_options.png` | `1b69342fbc947a381b51c252b67df4e48781e3e2091e5b2143e1ec6b3f1bf8ec` |
| `Sonbahar Temalı Piksel Kıyafet Paneli.png` | `assets/ui/character_customization/clothing_options.png` | `d8acec6d4b72306f6268234ac2e73fc9de327d161d2b80698401c083716ebe0e` |
| `manchar.jpeg` | `assets/characters/player/manchar.jpeg` | `e4c99cfb0a60f4b5b9f2c8cf88189541b7d434c3449212f5ad8185a1d8f595ad` |
| `villager.png` | `assets/characters/villagers/villager.png` | `61a72f3fda778931543114d83e1be30da2d1bef5907e2752673ea9553823be47` |
| `assets/sailboat_hull.png` | `assets/vehicles/sailboat_hull.png` | `3d4f6aab85d602216e0602762a3aaa7c55e5d2acd1a4670c3eaf4c89e9535289` |
| `bossanim.png` | `assets/bosses/platanus/bossanim.png` | `d385c5c66c919f0e9b9cecf5da5826d0c39a8351cb05c27f4fecb0ed9f250724` |
| `bosstile.png` | `assets/bosses/platanus/bosstile.png` | `5d809bf2c8a7ef57f784e6517ac221600e21385520be388ec181602f9ae2dda4` |
| `logo.png` (opaque, dark backdrop) | `assets/ui/menus/edge_of_winter_logo.png` (backdrop keyed to alpha, cropped) | `8a46fadbc48cc3a985c90c4140079f2f2879062b093d1fc8e2fc720c1a16d1e9` |
| `menumusic.wav` | `assets/audio/music/main_menu.wav` | unchanged file |

The untouched `logo.png` source and the previous title logo are preserved in
`.backups/menu-logo/`.
