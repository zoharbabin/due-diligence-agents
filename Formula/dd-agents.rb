class DdAgents < Formula
  include Language::Python::Virtualenv

  desc "AI-powered forensic due diligence analysis for M&A deal teams"
  homepage "https://github.com/zoharbabin/due-diligence-agents"
  url "https://files.pythonhosted.org/packages/a1/18/dfb6c92c3b86e80ce2aa30c16917e330373c55f3399c87896826347de3c2/dd_agents-0.5.0.tar.gz"
  sha256 "0a436d5d6a990626a5b30a446d9113d973a6ded03473449dc2bdd3b1425d9fbb"
  license "Apache-2.0"

  depends_on "python@3.12"

  def install
    virtualenv_create(libexec, "python3.12")
    system libexec/"bin/python", "-m", "pip", "install", "--verbose", buildpath
    bin.install_symlink Dir[libexec/"bin/dd-agents"]
  end

  test do
    assert_match version.to_s, shell_output("#{bin}/dd-agents version")
  end
end
