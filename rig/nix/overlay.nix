final: prev:

let
  inherit (final) buildPythonPackage;
  inherit (prev.pkgs) fetchurl autoPatchelfHook stdenv expat libGL libx11 zlib;

  wheel = args: buildPythonPackage ({ format = "wheel"; } // args);

  nativeLibs = [
    stdenv.cc.cc.lib
    expat
    libGL
    libx11
    zlib
  ];
in
{
  cadquery-ocp-novtk = wheel {
    pname = "cadquery-ocp-novtk";
    version = "8.0.1.1.0";

    src = fetchurl {
      url = "https://files.pythonhosted.org/packages/f5/a2/44043f9f2ff482a40aa43726c745d4215c6e1fec0e6ca3868169ea5c9b1c/cadquery_ocp_novtk-8.0.1.1.0-cp314-cp314-manylinux_2_28_x86_64.whl";
      hash = "sha256-fWpkUZUJBb8Z6fNpAJ+JzPFyhyA6Cc2qAo8BCoojylk=";
    };

    nativeBuildInputs = [ autoPatchelfHook ];
    buildInputs = nativeLibs;

    dependencies = [ final.cadquery-ocp-proxy ];

    pythonImportsCheck = [ "OCP" ];
  };

  cadquery-ocp-proxy = wheel {
    pname = "cadquery-ocp-proxy";
    version = "8.0.1.1.0";

    src = fetchurl {
      url = "https://files.pythonhosted.org/packages/13/5e/29c3d8c4b290dee82387468a33ac06c663518a167963cdb9ff48e6bbd8f9/cadquery_ocp_proxy-8.0.1.1.0-py3-none-any.whl";
      hash = "sha256-mMcbtgz7ZRr+F5sTSriFgP11OE/ODMbWM/cnACzRir0=";
    };
  };

  lib3mf = wheel {
    pname = "lib3mf";
    version = "2.5.0";

    src = fetchurl {
      url = "https://files.pythonhosted.org/packages/88/83/8b987ba95ac0ed9cc7e9c407a579bf43eff6349b1792b4a66c992ce4f76b/lib3mf-2.5.0-py3-none-manylinux2014_x86_64.whl";
      hash = "sha256-tMAAM8R8/qyTt9qgaftG6N6kOR1VIrec1un2r3XjMBM=";
    };

    nativeBuildInputs = [ autoPatchelfHook ];
    buildInputs = nativeLibs;

    pythonImportsCheck = [ "lib3mf" ];
  };

  ocpsvg = wheel {
    pname = "ocpsvg";
    version = "0.7.0";

    src = fetchurl {
      url = "https://files.pythonhosted.org/packages/f1/a5/4143c35ee979c5decc985ba4621f50fae1ec6977adf8ab0429c2a74be668/ocpsvg-0.7.0-py3-none-any.whl";
      hash = "sha256-pHa7SLay4tnx86Y1b95Xk3PWgWGLOaatnJmoCKAROZc=";
    };

    dependencies = [
      final.cadquery-ocp-novtk
      final.svgelements
    ];

    pythonImportsCheck = [ "ocpsvg" ];
  };

  ocp-gordon = wheel {
    pname = "ocp_gordon";
    version = "0.3.1";

    src = fetchurl {
      url = "https://files.pythonhosted.org/packages/3e/dc/ffc8307cd048f4f1e28d95cff6fe694af74f2bae771af6da272701d9646a/ocp_gordon-0.3.1-py3-none-any.whl";
      hash = "sha256-XfFMOAMtzKWCuniOU/jS6LOaZGpep4agMJ6ElLMGGoE=";
    };

    dependencies = [
      final.cadquery-ocp-novtk
      final.numpy
      final.scipy
    ];

    pythonImportsCheck = [ "ocp_gordon" ];
  };

  trianglesolver = wheel {
    pname = "trianglesolver";
    version = "1.2";

    src = fetchurl {
      url = "https://files.pythonhosted.org/packages/ff/8e/43d45cf3e18e3f455e4b5ab333a7c27b8e38c4e535f7346b7148ce08eb65/trianglesolver-1.2-py3-none-any.whl";
      hash = "sha256-qgkDw3CLTitJbwbUkMrnLG/2J0sA0e3OQg/Po7K3ZoI=";
    };

    pythonImportsCheck = [ "trianglesolver" ];
  };

  yacv-server = wheel {
    pname = "yacv_server";
    version = "0.12.2";

    src = fetchurl {
      url = "https://files.pythonhosted.org/packages/41/1a/ed20a6d97d18cb794dee3ac5532840cb5b77f49e7ea85899985be8efc6b6/yacv_server-0.12.2-py3-none-any.whl";
      hash = "sha256-2QErTJWj9e+Y3U6xtNjjG/gMV1UDTFq6zpwMGDEsu64=";
    };

    dependencies = [
      final.build123d
      final.pillow
      final.pygltflib
    ];

    pythonImportsCheck = [ "yacv_server" ];
  };

  build123d = wheel {
    pname = "build123d";
    version = "0.13.0";

    src = fetchurl {
      url = "https://files.pythonhosted.org/packages/16/a2/da58cdab8a6978376d66c909b06f4a1c9aafbd23163540741c75a51b675e/build123d-0.13.0-py3-none-any.whl";
      hash = "sha256-F38RTl8FFAVBiRNDRtOGxwBASPjlhDC5uEt0oE+8lP4=";
    };

    pythonRelaxDeps = [ "webcolors" ];

    dependencies = [
      final.anytree
      final.bd-materials
      final.fonttools
      final.threejs-materials
      final.cadquery-ocp-novtk
      final.ezdxf
      final.ipython
      final.lib3mf
      final.numpy
      final.ocp-gordon
      final.ocpsvg
      final.requests
      final.scikit-learn
      final.scipy
      final.svgpathtools
      final.sympy
      final.trianglesolver
      final.typing-extensions
      final.webcolors
    ];

    pythonImportsCheck = [ "build123d" ];
  };

  threejs-materials = wheel {
    pname = "threejs_materials";
    version = "1.2.5";

    src = fetchurl {
      url = "https://files.pythonhosted.org/packages/d5/ea/d2980e85afcc62e2a9c032c012009e3d50ec15f9b66ec1097463e65aa55e/threejs_materials-1.2.5-py3-none-any.whl";
      hash = "sha256-5iImQ4gEX6NWErUU3a7eyyE4McmKoLFAoQG78/3VJ6Y=";
    };

    dependencies = [
      final.numpy
      final.pillow
      final.platformdirs
      final.pygltflib
      final.requests
    ];

    pythonImportsCheck = [ "threejs_materials" ];
  };

  bd-materials = wheel {
    pname = "bd_materials";
    version = "0.2.6";

    src = fetchurl {
      url = "https://files.pythonhosted.org/packages/18/61/118b3c58f74724b6d11b86a53d63eefbe988747d3291d763d99652263f11/bd_materials-0.2.6-py3-none-any.whl";
      hash = "sha256-Hu6HheC3Z9y6OXFL4yaUvFcM7wzXeIgGNSXiB6gBLRo=";
    };

    pythonRelaxDeps = [ "webcolors" ];

    dependencies = [
      final.threejs-materials
      final.webcolors
    ];

    pythonImportsCheck = [ "bd_materials" ];
  };
}
