{
  pkgs,
  homeManager,
  popupInput,
}:

let
  inherit (pkgs) lib;
  evaluate =
    fnottEnabled: settings:
    (import (homeManager + "/modules") {
      inherit pkgs;
      configuration = {
        imports = [ (import ../nix/home-manager.nix { fzf-popup = popupInput; }) ];
        home = {
          username = "notification-test";
          homeDirectory = "/home/notification-test";
          stateVersion = "24.11";
        };
        services.fnott.enable = fnottEnabled;
        services.notification-history = settings;
      };
    }).config;
  enabled = evaluate true { enable = true; };
  disabled = evaluate false { };
  optIn = evaluate true { };
  explicitlyDisabled = evaluate true { enable = false; };
  explicitlyEnabled = evaluate false { enable = true; };
  custom = evaluate true {
    enable = true;
    package = pkgs.hello;
    maxEntries = 250;
  };
  results = lib.runTests {
    testModuleIsOptIn = {
      expr = optIn.services.notification-history.enable;
      expected = false;
    };
    testExplicitEnable = {
      expr = [
        enabled.services.notification-history.enable
        disabled.services.notification-history.enable
      ];
      expected = [
        true
        false
      ];
    };
    testDisableRemovesService = {
      expr = builtins.hasAttr "notification-history" explicitlyDisabled.systemd.user.services;
      expected = false;
    };
    testCanEnableIndependently = {
      expr = builtins.hasAttr "notification-history" explicitlyEnabled.systemd.user.services;
      expected = true;
    };
    testServiceUsesConfiguredPackage = {
      expr = custom.systemd.user.services.notification-history.Service.ExecStart;
      expected = [ "${pkgs.hello}/bin/notification-history listen" ];
    };
    testSessionLifecycle = {
      expr = {
        inherit (enabled.systemd.user.services.notification-history.Unit) After PartOf;
        inherit (enabled.systemd.user.services.notification-history.Install) WantedBy;
      };
      expected = {
        After = [ "graphical-session-pre.target" ];
        PartOf = [ enabled.wayland.systemd.target ];
        WantedBy = [ enabled.wayland.systemd.target ];
      };
    };
    testDataDirectoryAndRestart = {
      expr = {
        inherit (enabled.systemd.user.services.notification-history.Service) Environment Restart UMask;
      };
      expected = {
        Environment = [
          "XDG_DATA_HOME=/home/notification-test/.local/share"
          "NOTIFICATION_HISTORY_MAX_ENTRIES=100"
        ];
        Restart = "on-failure";
        UMask = "0077";
      };
    };
    testCustomRetention = {
      expr = custom.systemd.user.services.notification-history.Service.Environment;
      expected = [
        "XDG_DATA_HOME=/home/notification-test/.local/share"
        "NOTIFICATION_HISTORY_MAX_ENTRIES=250"
      ];
    };
    testRejectsInvalidRetention = {
      expr =
        map
          (
            value:
            (builtins.tryEval (evaluate true { maxEntries = value; }).services.notification-history.maxEntries)
            .success
          )
          [
            0
            (-1)
            "100"
          ];
      expected = [
        false
        false
        false
      ];
    };
  };
in
assert lib.assertMsg (results == [ ]) (builtins.toJSON results);
true
