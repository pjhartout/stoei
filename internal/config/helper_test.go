package config

import "gopkg.in/yaml.v3"

// rawYAML marshals c to YAML without clamping, so tests can feed deliberately
// out-of-range values through the pure Load path. (Marshal clamps; this does not.)
func rawYAML(c Config) ([]byte, error) {
	return yaml.Marshal(c)
}
