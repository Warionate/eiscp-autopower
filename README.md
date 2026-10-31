# eiscp-autopower

Turn an Onkyo / Pioneer / Integra network receiver on and off together with a Windows PC.

[日本語](#日本語)

The receiver is controlled over the network with eISCP (TCP 60128), so no IR blaster or
HDMI-CEC is needed. A small background process watches the PC and decides:

| When | What it does |
|---|---|
| Logon, unlock, resume from sleep by the user | Receiver in standby → power on, select the PC input, set the volume (optional) |
| The PC starts playing sound | Same as above |
| Silence for N minutes (default 10) | Standby, **only if the receiver is still on the PC input** |
| Sleep, shutdown | Same as above |

It never takes the receiver away from someone else: if the receiver is already on with
another input (TV, Bluetooth, streaming…), it is left alone, and it is never switched off
unless it is on the PC input. Wake-on-LAN or timer wakeups do not turn it on.

### Why it is built this way

- **One process, no polling of Windows events.** It listens for session (lock/unlock) and
  power (suspend/resume) notifications through a hidden window, and watches the output peak
  level through the Windows audio API.
- **Sleep has no time for a round trip.** Windows gives an application only a moment before
  it suspends, and the network is already going down. The agent remembers the receiver state
  (polled every minute) and, on suspend, sends the standby command without waiting for a reply.
- **Resume has no DNS yet.** The receiver address is resolved once and kept, and the wake-up
  after resume is retried until the network is back.

## Supported devices

Anything that speaks **eISCP** (Onkyo's network control protocol on TCP 60128) should work.
Only the first row has actually been tested; please open an issue to report other models.

| Status | Devices |
|---|---|
| ✅ Tested | Pioneer **HM76** (network CD receiver), optical input |
| 🟡 Expected to work (eISCP) | Onkyo network AV receivers (TX-NR / TX-RZ series) and network stereo receivers (TX-8xxx) |
| 🟡 Expected to work (eISCP) | Pioneer models built on the Onkyo platform: VSX-LX / VSX-S / SC-LX AV receivers (2016 and later), XC-HM / X-HM network CD receivers |
| 🟡 Expected to work (eISCP) | Integra DRX / DTR / DTM series |
| ❌ Not supported | Older Pioneer AV receivers that use Pioneer's own IP control (port 23 / 8102, `PO` / `PF` commands) instead of eISCP |
| ❌ Not supported | Other brands (Denon, Marantz, Yamaha, Sony…), which use different protocols |

How to check your receiver: put its address in `config.json` and run `install.ps1`.
It prints the power, input and volume before registering anything; if that works, the agent will work.
The receiver must allow power-on over the network ("Network Standby" or a similar setting).

## Requirements

- Windows 10 / 11
- Python 3.10+ from python.org (tested with 3.13). The installer creates its own virtual
  environment (`.venv`) in the folder, so nothing is installed into your global Python.
- A receiver that speaks eISCP (most Onkyo, Pioneer and Integra network models).
  Enable "Network Standby" (or similar) on the receiver so it can be powered on over the network.

## Install

```powershell
git clone https://github.com/Warionate/eiscp-autopower.git
cd eiscp-autopower
copy config.example.json config.json
notepad config.json        # set "host" to your receiver's IP or host name
powershell -ExecutionPolicy Bypass -File install.ps1
```

`install.ps1` creates `.venv`, installs the requirements into it, checks that the receiver
answers, and registers a scheduled task that starts the agent at logon (and restarts it if it
crashes). Run it again after changing `config.json` or pulling a new version.
`uninstall.ps1` removes the task; delete the folder to remove everything.

Put the folder somewhere that is **not** synchronised by OneDrive or similar, so the path does
not change under the scheduled task.

## Configuration

`config.json` (only `host` is required):

| Key | Default | Meaning |
|---|---|---|
| `host` | – | Receiver IP or host name. A fixed address (DHCP reservation) is recommended |
| `pc_input` | `"optical"` | Input the PC is connected to, as named by [onkyo-eiscp](https://github.com/miracle2k/onkyo-eiscp) (`optical`, `coaxial`, `pc`, `usb-dac-in`, …). Check with `status` |
| `wake_volume` | `null` | Volume set when the agent powers the receiver on. `null` leaves it unchanged |
| `wake_on_unlock` | `true` | Power on at logon, unlock and resume |
| `wake_on_sound` | `true` | Power on when sound starts |
| `off_on_sleep` | `true` | Standby before sleep and shutdown |
| `silence_minutes` | `10` | Standby after this many silent minutes. `0` disables it |
| `audio_threshold` | `1e-5` | Peak level that counts as sound |
| `log_file` | `"eiscp-autopower.log"` | Relative to the script folder. Rotated at 1 MB × 3 |

## Manual commands

```powershell
.venv\Scripts\python eiscp_autopower.py status   # power, input, volume
.venv\Scripts\python eiscp_autopower.py wake     # power on if in standby (leaves other inputs alone)
.venv\Scripts\python eiscp_autopower.py pc       # force: power on + PC input + volume, even if another input is in use
.venv\Scripts\python eiscp_autopower.py off      # standby if on the PC input
```

`pc` makes a handy desktop shortcut: target `"<folder>\.venv\Scripts\pythonw.exe" "<folder>\eiscp_autopower.py" pc`.

## Troubleshooting

Look at `eiscp-autopower.log` next to the script.

- `off(sleep): standby sent` – the sleep path worked.
- `off(sleep): state unknown` – the agent could not reach the receiver in the last ten minutes.
- `wake(...): already on, input [...] - leave it` – expected when the receiver is in use on another input.
- No `sound started` lines – the default playback device may not be the one connected to the
  receiver; the agent measures the default output device.

## License

MIT

---

## 日本語

Windows PC に合わせて、Onkyo / Pioneer / Integra のネットワーク対応レシーバーの電源を入れたり切ったりします。

操作はネットワーク越しの eISCP（TCP 60128）で行うので、赤外線リモコンや HDMI-CEC は要りません。
常駐 1 本が PC の様子を見て判断します。

| いつ | すること |
|---|---|
| ログオン・ロック解除・利用者の操作によるスリープ復帰 | レシーバーがスタンバイなら、電源オン → PC の入力に切替 → 音量を設定（任意） |
| PC が音を出し始めたとき | 同上 |
| 無音が N 分（既定 10 分）続いたとき | スタンバイ。**入力が PC のままのときだけ** |
| スリープ・シャットダウン | 同上 |

ほかの人が使っているときは横取りしません。すでに別の入力（テレビ・Bluetooth・ネット配信など）で点いていれば何もせず、
入力が PC のとき以外は切りません。Wake-on-LAN やタイマーでの復帰では点けません。

### 作りの要点

- **常駐 1 本。** ロック・解除やスリープ・復帰は、隠しウィンドウで Windows からの通知を受けます。音は Windows の音声 API で出力のピーク値を測ります。
- **スリープ直前は問い合わせる時間がない。** Windows がスリープ前にアプリへ与える猶予はわずかで、ネットワークも落ち始めています。そこで普段から 1 分おきにレシーバーの状態を覚えておき、スリープ直前はその記憶で判断して、スタンバイの命令を返事を待たずに送ります。
- **復帰直後は名前が引けない。** レシーバーの IP は一度引いたら覚えておき、復帰後の電源オンはネットワークが戻るまでやり直します。

### 対応機器

**eISCP**（Onkyo のネットワーク操作の方式。TCP 60128）に対応した機器なら動くはずです。
実際に試したのは 1 行目だけです。ほかの機種で動いた・動かなかったら issue で教えてください。

| 状況 | 機器 |
|---|---|
| ✅ 確認済み | Pioneer **HM76**（ネットワーク CD レシーバー）、光デジタル入力 |
| 🟡 動くはず（eISCP） | Onkyo のネットワーク対応 AV アンプ（TX-NR・TX-RZ シリーズ）、ネットワーク対応ステレオレシーバー（TX-8xxx） |
| 🟡 動くはず（eISCP） | Onkyo と共通の作りの Pioneer 製品：AV アンプ VSX-LX・VSX-S・SC-LX（2016 年以降）、ネットワーク CD レシーバー XC-HM・X-HM |
| 🟡 動くはず（eISCP） | Integra の DRX・DTR・DTM シリーズ |
| ❌ 非対応 | eISCP ではなく Pioneer 独自の IP 操作（23 番・8102 番、`PO`・`PF` コマンド）を使う古い Pioneer の AV アンプ |
| ❌ 非対応 | ほかのメーカー（Denon・Marantz・Yamaha・Sony など）。操作の方式が違う |

自分の機器で使えるかは、`config.json` にレシーバーのアドレスを書いて `install.ps1` を実行すれば分かります。
登録の前に電源・入力・音量を表示するので、それが出れば使えます。

### 入れ方

python.org の Python 3.10 以上を入れておいてください（確認は 3.13）。ライブラリはフォルダの中の仮想環境（`.venv`）に入るので、普段使っている Python には何も入りません。

```powershell
git clone https://github.com/Warionate/eiscp-autopower.git
cd eiscp-autopower
copy config.example.json config.json
notepad config.json        # "host" にレシーバーの IP かホスト名を書く
powershell -ExecutionPolicy Bypass -File install.ps1
```

`install.ps1` は、`.venv` を作ってライブラリを入れ、レシーバーが応答するか確かめてから、ログオン時に起動し落ちたら起動し直すタスクを登録します。`config.json` を変えたときや、新しい版を取ってきたときはもう一度実行してください。外すときは `uninstall.ps1` で、フォルダを消せば全部消えます。

置き場所は OneDrive などで**同期しないフォルダ**にしてください。同期フォルダに置くと、パスが変わってタスクが動かなくなることがあります。

レシーバー側では「ネットワークスタンバイ」（機種によって名前は違います）を有効にしてください。これが無効だと、ネットワーク越しに電源を入れられません。

設定項目・手動コマンド・困ったときは、上の英語の節と同じです（`config.json` で必須なのは `host` だけ）。

