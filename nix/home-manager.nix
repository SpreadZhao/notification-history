{ fzf-popup }:
{
  config,
  lib,
  pkgs,
  ...
}:

let
  cfg = config.services.notification-history;
  sessionTarget = config.wayland.systemd.target;
in
{
  options.services.notification-history = {
    enable = lib.mkEnableOption "persistent desktop notification history";
    package = lib.mkOption {
      type = lib.types.package;
      default = pkgs.callPackage ./package.nix {
        fzf-popup = fzf-popup.packages.${pkgs.stdenv.hostPlatform.system}.default;
      };
      description = "Notification history application and listener.";
    };
  };

  config = lib.mkIf cfg.enable {
    home.packages = [ cfg.package ];
    systemd.user.services.notification-history = {
      Unit = {
        Description = "Save desktop notifications to SQLite";
        After = [ "graphical-session-pre.target" ];
        PartOf = [ sessionTarget ];
      };
      Service = {
        Type = "simple";
        ExecStart = "${cfg.package}/bin/notification-history listen";
        Environment = [ "XDG_DATA_HOME=${config.xdg.dataHome}" ];
        Restart = "on-failure";
        RestartSec = 2;
        UMask = "0077";
        StandardOutput = "journal";
        StandardError = "journal";
      };
      Install.WantedBy = [ sessionTarget ];
    };
  };
}
