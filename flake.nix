{
  description = "notification-history — standalone Bash application";
  inputs = {
    nixpkgs.url = "github:nixos/nixpkgs/nixos-unstable";
    home-manager = {
      url = "github:nix-community/home-manager/master";
      inputs.nixpkgs.follows = "nixpkgs";
    };
    fzf-popup = {
      url = "github:SpreadZhao/fzf-popup/main";
      inputs.nixpkgs.follows = "nixpkgs";
    };
  };
  outputs =
    { self, nixpkgs, ... }@inputs:
    let
      systems = [
        "x86_64-linux"
        "aarch64-linux"
      ];
      eachSystem = nixpkgs.lib.genAttrs systems;
      mkPkgs = system: import nixpkgs { inherit system; };
    in
    {
      packages = eachSystem (
        system:
        let
          pkgs = mkPkgs system;
          package = pkgs.callPackage ./nix/package.nix {
            fzf-popup = inputs.fzf-popup.packages.${system}.default;
          };
        in
        {
          default = package;
          notification-history = package;
        }
      );
      apps = eachSystem (system: {
        default = {
          type = "app";
          program = "${self.packages.${system}.default}/bin/notification-history";
        };
        notification-history = self.apps.${system}.default;
      });
      homeManagerModules.default = import ./nix/home-manager.nix { inherit (inputs) fzf-popup; };
      formatter = eachSystem (system: (mkPkgs system).nixfmt);
      devShells = eachSystem (
        system:
        let
          pkgs = mkPkgs system;
        in
        {
          default = pkgs.mkShell {
            packages = with pkgs; [
              bash
              coreutils
              systemd
              jq
              sqlite
              util-linux
              wl-clipboard
              dbus
              fzf
              python3
              shellcheck
              nixfmt
            ];
          };
        }
      );
      checks = eachSystem (
        system:
        let
          pkgs = mkPkgs system;
          passed = import ./tests/module.nix {
            inherit pkgs;
            homeManager = inputs.home-manager.outPath;
            popupInput = inputs.fzf-popup;
          };
        in
        {
          default =
            assert passed;
            pkgs.runCommand "notification-history-checks"
              {
                nativeBuildInputs = with pkgs; [
                  bash
                  coreutils
                  systemd
                  jq
                  sqlite
                  util-linux
                  wl-clipboard
                  dbus
                  fzf
                  python3
                  shellcheck
                  nixfmt
                ];
                application = self.packages.${system}.default;
                REAL_FZF = "${pkgs.fzf}/bin/fzf";
                DBUS_SESSION_CONF = "${pkgs.dbus}/share/dbus-1/session.conf";
              }
              ''
                cp -R ${./.} source
                chmod -R u+w source
                cp ${inputs.fzf-popup}/src/fzf-popup source/src/fzf-popup
                cd source
                patchShebangs src tests
                export PATH="$PWD/src:$PATH"
                "$application/bin/notification-history" --help
                shellcheck src/*
                for file in src/* ; do bash -n "$file"; done
                nixfmt --check flake.nix nix/*.nix tests/module.nix
                python3 tests/check.py
                touch "$out"
              '';
        }
      );
    };
}
