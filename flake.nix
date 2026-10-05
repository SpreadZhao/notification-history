{
  description = "notification-history — standalone Bash application";
  inputs = {
    nixpkgs.url = "github:nixos/nixpkgs/nixos-unstable";
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
              fzf
              neovim
              shellcheck
              nixfmt
            ];
          };
        }
      );
      # Building writeShellApplication already checks Bash syntax and ShellCheck.
      checks = eachSystem (system: {
        default = self.packages.${system}.default;
      });
    };
}
