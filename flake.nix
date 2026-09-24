{
  description = "TSM Desktop App for Linux: TradeSkillMaster auction data downloader";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
  };

  outputs =
    { self, nixpkgs }:
    let
      systems = [
        "x86_64-linux"
        "aarch64-linux"
      ];
      forAllSystems = fn: nixpkgs.lib.genAttrs systems (system: fn nixpkgs.legacyPackages.${system});

      # Keep in step with the version the release is tagged with.
      version = "1.1.16";
    in
    {
      overlays.default = final: _prev: {
        # APScheduler 4 is still a pre-release, so nixpkgs carries 3.x. The app
        # uses the 4.x AsyncScheduler API and will not run on 3.x.
        apscheduler4 = final.python3Packages.buildPythonPackage rec {
          pname = "apscheduler";
          version = "4.0.0a6";
          pyproject = true;

          src = final.fetchPypi {
            inherit pname version;
            hash = "sha256-UTRhfAKPCX3koJq77vxCYlywzjrctM5J10zCYFQIR2E=";
          };

          build-system = with final.python3Packages; [
            setuptools
            setuptools-scm
          ];

          dependencies = with final.python3Packages; [
            anyio
            attrs
            tenacity
            tzlocal
          ];

          # The upstream suite wants live database and broker services.
          doCheck = false;
          pythonImportsCheck = [ "apscheduler" ];

          meta = {
            description = "Task scheduling library for Python";
            homepage = "https://github.com/agronholm/apscheduler";
            license = final.lib.licenses.mit;
          };
        };

        tsm-app = final.python3Packages.buildPythonApplication {
          pname = "tsm-app";
          inherit version;
          pyproject = true;
          src = self;

          # hatch-vcs derives the version from git tags, and the store copy of
          # the source carries no git metadata, so it is passed in instead.
          SETUPTOOLS_SCM_PRETEND_VERSION = version;

          build-system = with final.python3Packages; [
            hatchling
            hatch-vcs
          ];

          dependencies = with final.python3Packages; [
            pyside6
            aiohttp
            pydantic
            aiosqlite
            keyring
            structlog
            tomli-w
            pyyaml
            typing-extensions
          ]
          ++ [ final.apscheduler4 ];

          # A Qt application needs its plugin paths wired up, which
          # buildPythonApplication does not do on its own. The hook is told to
          # keep its hands off so its arguments can be folded into the single
          # wrapper the Python builder already creates.
          # wrapQtAppsHook reads the plugin prefix off qtbase, and fails with
          # "qtPluginPrefix is unset" when it is not among the build inputs.
          buildInputs = [ final.qt6.qtbase ];
          nativeBuildInputs = [ final.qt6.wrapQtAppsHook ];
          dontWrapQtApps = true;
          preFixup = ''
            makeWrapperArgs+=("''${qtWrapperArgs[@]}")
          '';

          postInstall = ''
            install -Dm644 packaging/tsm-app.desktop \
              $out/share/applications/tsm-app.desktop
            for size in 16 32 48 128 256; do
              install -Dm644 "tsm/ui/assets/tsm_$size.png" \
                "$out/share/icons/hicolor/''${size}x''${size}/apps/tsm-app.png"
            done
          '';

          # The widget tests need a display stack, so they are left to CI.
          doCheck = false;
          pythonImportsCheck = [ "tsm" ];

          meta = {
            description = "TradeSkillMaster auction data downloader for World of Warcraft on Linux";
            homepage = "https://github.com/exceptionptr/tsm-app-linux";
            license = final.lib.licenses.mit;
            mainProgram = "tsm-app";
            platforms = final.lib.platforms.linux;
          };
        };
      };

      packages = forAllSystems (
        pkgs:
        let
          extended = pkgs.extend self.overlays.default;
        in
        {
          tsm-app = extended.tsm-app;
          apscheduler4 = extended.apscheduler4;
          default = extended.tsm-app;
        }
      );

      apps = forAllSystems (
        pkgs:
        let
          package = self.packages.${pkgs.stdenv.hostPlatform.system}.tsm-app;
        in
        {
          default = {
            type = "app";
            program = "${package}/bin/tsm-app";
            meta = package.meta;
          };
        }
      );

      devShells = forAllSystems (pkgs: {
        default = pkgs.mkShell {
          inputsFrom = [ (pkgs.extend self.overlays.default).tsm-app ];
          packages = with pkgs; [
            python3Packages.pytest
            python3Packages.pytest-asyncio
            ruff
            mypy
          ];
          shellHook = ''
            echo "TSM App dev shell. Run: python -m tsm"
          '';
        };
      });

      formatter = forAllSystems (pkgs: pkgs.nixfmt);
    };
}
