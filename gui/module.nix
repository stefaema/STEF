{ pkgs, ... }:

{
  description = "Operator GUI for the STEF project";

  python = ps: [
    ps.fastapi
    ps.uvicorn
    ps.jinja2
    ps.python-multipart
    ps.loguru
    ps.httpx
    ps.pytest
    ps.pytest-asyncio
    ps.pyserial
    (ps.toPythonModule (pkgs.esptool.override { python3Packages = ps; }))
  ];

  packages = [ pkgs.gettext pkgs.tailwindcss_4 ];
}
