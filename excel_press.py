#!/usr/bin/env python
# Copyright (c) 2015, Brandan [coldfusion]
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

import argparse
import math
import struct
import sys

def main():
	parser = argparse.ArgumentParser(description='Compress or decompress a VBA macro file')
	parser.add_argument('--raw', help='Output the VBA data as compressed (HEX)', action='store_true', required=False)
	mode = parser.add_mutually_exclusive_group(required=True)
	mode.add_argument('-c', '--compress', help='Compress the specified VBA macro file', required=False)
	mode.add_argument('-d', '--decompress', help='Decompressed the specified VBA macro file', required=False)
	args = parser.parse_args()

	if args.compress and args.raw:
		print('Raw output --raw can only be used with the -d decompress function!')
		return 0

	if args.compress:
		data = open(args.compress, 'rb').read()

		decompressed = CompressedVBA(data)
		compressed = decompressed.compress()
		print(compressed)
	else:
		macro_file = open(args.decompress, 'rb').read()
		print (decompress(macro_file, raw=args.raw))

# Decompression algorithm
def decompress(data, raw=False):
	search_string = '\x00Attribut'
	position = data.find(search_string)
	if position != -1 and data[position + len(search_string)] == 'e':
		position = -1

	compressed_data = data[position - 3:]

	if raw:
		return compressed_data

	# Actually decompress the data
	remainder = compressed_data[1:]

	decompressed = ''
	while len(remainder) != 0:
		decompressed_chunk, remainder = decompress_chunk(remainder)
		decompressed += decompressed_chunk

	return decompressed

def decompress_chunk(compressedchunk):
	if len(compressedchunk) < 2:
		return None, None

	header = ord(compressedchunk[0]) + ord(compressedchunk[1]) * 0x100
	size = (header & 0x0FFF) + 3
	data = compressedchunk[2:2 + size - 2]

	decompressed_chunk = ''

	while len(data) != 0:
		tokens, data = parse_token_sequence(data)
		for token in tokens:
			if len(token) == 1:
				decompressed_chunk += token
			else:
				number_of_offset_bits = offset_bits(decompressed_chunk)
				copy_token = ord(token[0]) + ord(token[1]) * 0x100
				offset = 1 + (copy_token >> (16 - number_of_offset_bits))
				length = 3 + (((copy_token << number_of_offset_bits) & 0xFFFF) >> number_of_offset_bits)
				copy = decompressed_chunk[-offset:]
				copy = copy[0:length]
				length_copy = len(copy)
				while length > length_copy:
					if length - length_copy >= length_copy:
						copy += copy[0:length_copy]
						length -= length_copy
					else:
						copy += copy[0:length - length_copy]
						length -= length - length_copy
				decompressed_chunk += copy
	return decompressed_chunk, compressedchunk[size:]

def offset_bits(data):
	number_of_bits = int(math.ceil(math.log(len(data), 2)))
	if number_of_bits < 4:
		number_of_bits = 4
	elif number_of_bits > 12:
		number_of_bits = 12
	return number_of_bits

def parse_token_sequence(data):
	flags = ord(data[0])
	data = data[1:]
	result = []

	for mask in [0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80]:
		if len(data) > 0:
			if flags & mask:
				result.append(data[0:2])
				data = data[2:]
			else:
				result.append(data[0])
				data = data[1:]

	return result, data

# Compression algorithm
class VBAStream:
	def __init__(self, data):
		self.data = data

class CompressedVBA(VBAStream):
	def compress(self):
		self.compressed_container = bytearray()
		self.compressed_current = 0
		self.compressed_chunk_start = 0
		self.decompressed_current = 0
		self.decompressed_buffer_end = len(self.data)
		self.decompressed_chunk_start = 0

		signature_byte = 0x01
		self.compressed_container.append(signature_byte)
		self.compressed_current = self.compressed_current + 1

		while self.decompressed_current < self.decompressed_buffer_end:
			self.compressed_chunk_start = self.compressed_current
			self.decompressed_chunk_start = self.decompressed_current
			self.compress_decompressed_chunk()

		return self.compressed_container

	def compress_decompressed_chunk(self):
		self.compressed_container.extend(bytearray(4096 + 2))
		compressed_end = self.compressed_chunk_start + 4098
		self.compressed_current = self.compressed_chunk_start + 2
		decompressed_end = self.decompressed_buffer_end

		if (self.decompressed_chunk_start + 4096) < self.decompressed_buffer_end:
			decompressed_end = (self.decompressed_chunk_start + 4096)

		while (self.decompressed_current < decompressed_end) and (self.compressed_current < compressed_end):
				self.compress_token_sequence(compressed_end, decompressed_end)

		if self.decompressed_current < decompressed_end:
			self.compress_raw_chunk(decompressed_end - 1)
			compressed_flag = 0
		else:
			compressed_flag = 1

		size = self.compressed_current - self.compressed_chunk_start
		header = 0x0000

		# Pack compressed chunk size
		temp1 = header & 0xF000
		temp2 = size - 3
		header = temp1 | temp2

		# Pack compressed chunk flag
		temp1 = header & 0x7FFF
		temp2 = compressed_flag << 15
		header = temp1 | temp2

		# Pack compressed chunk signature
		temp1 = header & 0x8FFF
		header_final = temp1 | 0x3000

		struct.pack_into("<H", self.compressed_container, self.compressed_chunk_start, header_final)

		if (self.compressed_current):
			self.compressed_container = self.compressed_container[0:self.compressed_current]

	def compress_token_sequence(self, compressed_end, decompressed_end):
		flag_byte_index = self.compressed_current
		token_flags = 0
		self.compressed_current = self.compressed_current + 1

		for index in range(0, 8):
			if ((self.decompressed_current < decompressed_end) and (self.compressed_current < compressed_end)):
				token_flags = self.compress_token(compressed_end, decompressed_end, index, token_flags)
		self.compressed_container[flag_byte_index] = token_flags

	def compress_token(self, compressed_end, decompressed_end, index, flags):
		offset = 0
		offset, length = self.matching(decompressed_end)

		if offset:
			if (self.compressed_current + 1) < compressed_end:
				copy_token = self.pack_copy_token(offset, length)
				struct.pack_into("<H", self.compressed_container, self.compressed_current, copy_token)

				# Set flag bit
				temp1 = 1 << index
				temp2 = flags & ~temp1
				flags = temp2 | temp1

				self.compressed_current = self.compressed_current + 2
				self.decompressed_current = self.decompressed_current + length
			else:
				self.compressed_current = compressed_end
		else:
			if self.compressed_current < compressed_end:
				self.compressed_container[self.compressed_current] = self.data[self.decompressed_current]
				self.compressed_current = self.compressed_current + 1
				self.decompressed_current = self.decompressed_current + 1
			else:
				self.compressed_current = compressed_end

		return flags

	def matching(self, decompressed_end):
		candidate = self.decompressed_current - 1
		best_length = 0

		while candidate >= self.decompressed_chunk_start:
			C = candidate
			D = self.decompressed_current
			L = 0
			while D < decompressed_end and (self.data[D] == self.data[C]):
				L = L + 1
				C = C + 1
				D = D + 1

			if L > best_length:
				best_length = L
				best_candidate = candidate
			candidate = candidate - 1

		if best_length >=  3:
			length_mask, off_set_mask, bit_count, maximum_length = self.copy_token_help()
			length = best_length
			if (maximum_length < best_length):
				length = maximum_length
			offset = self.decompressed_current - best_candidate
		else:
			length = 0
			offset = 0

		return offset, length

	def copy_token_help(self):
		difference = self.decompressed_current - self.decompressed_chunk_start
		bit_count = 0

		while ((1 << bit_count) < difference):
			bit_count +=1

		if bit_count < 4:
			bit_count = 4;

		length_mask = 0xFFFF >> bit_count
		off_set_mask = ~length_mask
		maximum_length = (0xFFFF >> bit_count) + 3

		return length_mask, off_set_mask, bit_count, maximum_length

	def pack_copy_token(self, offset, length):
		length_mask, off_set_mask, bit_count, maximum_length = self.copy_token_help()
		temp1 = offset - 1
		temp2 = 16 - bit_count
		temp3 = length - 3
		copy_token = (temp1 << temp2) | temp3

		return copy_token

	def compress_raw_chunk(self):
		self.compressed_current = self.compressed_chunk_start + 2
		self.decompressed_current  = self.decompressed_chunk_start
		pad_count = 4096
		last_byte = self.decompressed_chunk_start + pad_count
		if self.decompressed_buffer_end < last_byte:
			last_byte =  self.decompressed_buffer_end

		for index in range(self.decompressed_chunk_start, last_byte):
			self.compressed_container[self.compressed_current] = self.data[index]
			self.compressed_current = self.compressed_current + 1
			self.decompressed_current = self.decompressed_current + 1
			pad_count = pad_count - 1

		for index in range(0, pad_count):
			self.compressed_container[self.compressed_current] = 0x0;
			self.compressed_current = self.compressed_current + 1

if __name__ == '__main__':
	sys.exit(main())
