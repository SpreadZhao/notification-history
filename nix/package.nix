{
  writeShellApplication,
  coreutils,
  systemd,
  jq,
  sqlite,
  util-linux,
  fzf-popup,
  neovim,
  wl-clipboard,
}:

writeShellApplication {
  name = "notification-history";
  runtimeInputs = [
    coreutils
    systemd
    jq
    sqlite
    util-linux
    fzf-popup
    neovim
    wl-clipboard
  ];
  text = builtins.readFile ../src/notification-history;
  passthru = { inherit neovim; };
}
