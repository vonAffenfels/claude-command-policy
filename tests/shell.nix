{ pkgs ? import <nixpkgs> {} }:
pkgs.mkShell {
  buildInputs = [
    pkgs.python313
    pkgs.python313Packages.pytest
    pkgs.shfmt
    pkgs.git
  ];

  shellHook = ''
    echo "Test environment ready. Run: pytest"
  '';
}
