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
    version = "7.9.3.1.1";

    src = fetchurl {
      url = "https://files.pythonhosted.org/packages/f3/31/82baf17406c0a13f2eb98c1d46d09a640795fc7d6b373a69bc5f44344db3/cadquery_ocp_novtk-7.9.3.1.1-cp313-cp313-manylinux_2_31_x86_64.whl";
      hash = "sha256-/80E1O+gh9OqlCNgAgJloawOEkB717z+s35wtNHuct8=";
    };

    nativeBuildInputs = [ autoPatchelfHook ];
    buildInputs = nativeLibs;

    dependencies = [ final.cadquery-ocp-proxy ];

    pythonImportsCheck = [ "OCP" ];
  };

  cadquery-ocp-proxy = wheel {
    pname = "cadquery-ocp-proxy";
    version = "7.9.3.1.1";

    src = fetchurl {
      url = "https://files.pythonhosted.org/packages/30/c0/04e9363a99fee892de2776820e3dcf04f8825b6edc9580efe3416c9465a7/cadquery_ocp_proxy-7.9.3.1.1-py3-none-any.whl";
      hash = "sha256-ykFk7EtUlW2fw+aMZ9VVtUhsuWPC9x4Y3wBboWuSHJE=";
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
    version = "0.6.0";

    src = fetchurl {
      url = "https://files.pythonhosted.org/packages/a9/d7/27d2c9d5a2645fdda9e502a2a1a1cb5d4c9d137223ef76a43296eb7c152b/ocpsvg-0.6.0-py3-none-any.whl";
      hash = "sha256-XPxt6y9gLe2EVZZAnkH+j14bOJ4U6MxyfbCVXw6I3ns=";
    };

    dependencies = [
      final.cadquery-ocp-novtk
      final.svgelements
    ];

    pythonImportsCheck = [ "ocpsvg" ];
  };

  ocp-gordon = wheel {
    pname = "ocp_gordon";
    version = "0.2.2";

    src = fetchurl {
      url = "https://files.pythonhosted.org/packages/6c/d1/ee535cdbc502790dda6555e439ea8bcacdd38325859151769d109d307a94/ocp_gordon-0.2.2-py3-none-any.whl";
      hash = "sha256-ZBTpAaEQZaVug5yBtW9BgQC00Lgetaojux+Pcvl/8Jk=";
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
    version = "0.11.3";

    src = fetchurl {
      url = "https://files.pythonhosted.org/packages/bb/73/e0e4f9b9af9be15a079ae6689e2b91fd5a56b2646dcb5fea98a39fdf006b/yacv_server-0.11.3-py3-none-any.whl";
      hash = "sha256-V+fcEsWijomaXLXKoYJlpFKRVJuqsDuWSHFl1hqn0TU=";
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
    version = "0.11.1";

    src = fetchurl {
      url = "https://files.pythonhosted.org/packages/e7/f2/c466dbd4cb3aa75a192ba39f1a49058f828fcc0eb6f9cf6936ed6078308b/build123d-0.11.1-py3-none-any.whl";
      hash = "sha256-TpX6fMvcg+YkMTvkkufE9fDrLqHfNhMOtxi7DCWonhA=";
    };

    pythonRelaxDeps = [ "webcolors" ];

    dependencies = [
      final.anytree
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
}
