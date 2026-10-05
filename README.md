# Notification history

`notification-history` is a Bash application packaged with its runtime dependencies.
Its Home Manager service is opt-in. Enable it explicitly in your configuration.
After applying the configuration, the listener starts with the graphical session.

- Open history: `notification-history` or `notification-history browse`.
- Preview a record: `notification-history preview ID`.
- View its title and body in read-only Neovim: `notification-history view ID`.
- Copy its title and body: `notification-history copy ID`.
- Inspect the listener: `systemctl --user status notification-history.service`.
- Read listener errors: `journalctl --user -u notification-history.service`.

The menu uses the independent `fzf-popup` package. Configure its launcher to
open your preferred terminal and configure floating behavior in your window manager.
Enter replaces the menu with read-only Neovim in the same terminal, showing the
title and full body separated by a newline (only the title if the body is empty).
Your existing Neovim configuration is used, with word wrapping enabled for the
notification window (`wrap` and `linebreak`). Quit Neovim to close the popup;
Escape cancels the menu. Neither action changes the clipboard. The explicit
`copy ID` command remains available.

Viewing writes the original text into a private temporary file, which is deleted
when Neovim exits, including on editor failure. Swap files, ShaDa history and
notification modelines are disabled. List and preview text still filters terminal
control characters; stored text, editor contents and explicit copies preserve it.
The database is `${XDG_DATA_HOME:-$HOME/.local/share}/notification-history/history.sqlite3`.

The listener records incoming desktop `Notify` requests, including requests sent
while fnott is paused. It starts recording when the service starts; it cannot
recover notifications from before that time. Each update is a separate record,
and records are retained across service restarts without automatic pruning.

Home Manager options:

```nix
services.notification-history.enable = true;
# services.notification-history.package = anotherNotificationHistoryPackage;
```

Build the standalone package and run its isolated integration checks:

```sh
nix build
nix flake check
```

For untracked additions, use `path:$PWD` as the flake reference.

## Flake integration

Add `github:SpreadZhao/notification-history/main` as an input and import
`inputs.notification-history.homeManagerModules.default`. Its
`services.notification-history.enable` defaults to false. Both its `nixpkgs`
and `home-manager` inputs can follow your corresponding root inputs.
The `fzf-popup` input can also follow a root input of the same name.

The package can be configured independently of the service:

```nix
package = inputs.notification-history.packages.${pkgs.stdenv.hostPlatform.system}.default.override {
  fzf-popup = yourConfiguredPopupPackage;
  neovim = yourConfiguredNeovimPackage;
};
```

For a terminal window, configure `FZF_POPUP_LAUNCHER` in your environment or
wrap `fzf-popup` with its default launcher. The launcher receives argv and waits
for completion; see the [fzf-popup documentation](https://github.com/SpreadZhao/fzf-popup).
Without a launcher, browsing uses the current terminal. No Foot or Niri dependency
is included here. The listener and database commands do not require a terminal.

Packages, apps, checks, formatter and development shells support x86_64-linux
and aarch64-linux. `nix develop` supplies runtime and test dependencies;
`tests/check.py` runs its own private D-Bus session.
