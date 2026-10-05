{
  writeShellApplication,
  coreutils,
  systemd,
  jq,
  sqlite,
  util-linux,
  fzf-popup,
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
    wl-clipboard
  ];
  text = builtins.readFile ../src/notification-history;
}
